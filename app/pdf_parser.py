import io
import os
import re
from dataclasses import dataclass

import fitz
from pypdf import PdfReader, PdfWriter

CIERRE_PATTERN = re.compile(r"Cotización adicional de solidaridad", re.IGNORECASE)

# Patrón genérico para detectar CUALQUIER NIF/CIF con formato reconocible en el PDF,
# aunque no sea el esperado — se usa solo para dar una pista útil en el mensaje de error
# ("parece que has subido el PDF de otra empresa").
NIF_GENERICO_PATTERN = re.compile(r"NIF\.\s*([A-Z0-9]{8,9})")

TRABAJADOR_HEADER = "TRABAJADOR/A"
CATEGORIA_HEADER = "CATEGORIA"
ANTIGUEDAD_HEADER = "ANTIGUEDAD"
DNI_HEADER = "D.N.I."
PERIODO_HEADER = "PERIODO"

DNI_NIE_PATTERN = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")

# Ej.: "MENS 01 JUN 26 a 30 JUN 26" -> captura mes abreviado y año de 2 dígitos del inicio.
PERIODO_PATTERN = re.compile(r"\bMENS\s+\d{1,2}\s+([A-Z]{3})\s+(\d{2})\b")
MES_ABREVIADO_A_NUMERO = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


class ParserError(Exception):
    """Anclajes esperados no encontrados: requiere revisión manual."""


class SinNominasDetectadas(ParserError):
    """No se encontró ningún anclaje de nómina para el NIF esperado.

    Puede ser un PDF incorrecto, o el PDF correcto de OTRA empresa: si se detecta algún
    otro NIF reconocible en el archivo, se guarda en `nif_alternativo` para poder avisar
    de que quizás se ha seleccionado la empresa equivocada.
    """

    def __init__(self, nif_esperado: str, nif_alternativo: str | None = None):
        self.nif_esperado = nif_esperado
        self.nif_alternativo = nif_alternativo
        mensaje = f"No se encontró ningún anclaje 'NIF. {nif_esperado}'"
        if nif_alternativo:
            mensaje += f" (se detectó otro NIF distinto: {nif_alternativo})"
        super().__init__(mensaje)


@dataclass
class NominaDetectada:
    pagina_inicio: int
    pagina_fin: int
    nombre_trabajador: str
    dni_nie: str | None  # None si esa nómina concreta no tenía un D.N.I. con formato reconocible


def _fila_bajo_cabecera(words, header_y: float, x_min: float, x_max: float) -> str:
    candidatos = [(x0, y0, w) for x0, y0, x1, y1, w, *_ in words if x_min <= x0 < x_max and y0 > header_y + 2]
    if not candidatos:
        return ""

    fila_y = min(y0 for _, y0, _ in candidatos)
    fila_datos = sorted((x0, w) for x0, y0, w in candidatos if abs(y0 - fila_y) < 3)
    return " ".join(w for _, w in fila_datos).strip()


def _extraer_nombre_trabajador(page: fitz.Page) -> str:
    words = page.get_text("words")

    trabajador_x = next((x0 for x0, y0, x1, y1, w, *_ in words if w == TRABAJADOR_HEADER), None)
    categoria_x = next((x0 for x0, y0, x1, y1, w, *_ in words if w == CATEGORIA_HEADER), None)
    if trabajador_x is None or categoria_x is None:
        raise ParserError(
            f"No se encontraron las cabeceras {TRABAJADOR_HEADER}/{CATEGORIA_HEADER} "
            f"en la página {page.number}"
        )

    limite_derecho = (trabajador_x + categoria_x) / 2
    header_y = min(y0 for x0, y0, x1, y1, w, *_ in words if w == TRABAJADOR_HEADER)

    nombre = _fila_bajo_cabecera(words, header_y, x_min=0, x_max=limite_derecho)
    if not nombre:
        raise ParserError(f"No se encontró la fila de datos del trabajador en la página {page.number}")
    return nombre


def _extraer_dni_trabajador(page: fitz.Page) -> str | None:
    """Devuelve el D.N.I./N.I.E. del trabajador, o None si no se pudo extraer con formato reconocible.

    A diferencia del nombre, la ausencia de un D.N.I. válido en una nómina concreta
    no es un error fatal del parseo: se deja que el matcher decida cómo tratarlo
    (normalmente cayendo a un emparejamiento por nombre para ese caso puntual).
    """
    words = page.get_text("words")

    antiguedad_x = next((x0 for x0, y0, x1, y1, w, *_ in words if w == ANTIGUEDAD_HEADER), None)
    dni_x = next((x0 for x0, y0, x1, y1, w, *_ in words if w == DNI_HEADER), None)
    if antiguedad_x is None or dni_x is None:
        return None

    limite_izquierdo = (antiguedad_x + dni_x) / 2
    header_y = min(y0 for x0, y0, x1, y1, w, *_ in words if w == DNI_HEADER)

    dni_candidato = _fila_bajo_cabecera(words, header_y, x_min=limite_izquierdo, x_max=float("inf"))
    dni_candidato = dni_candidato.replace(" ", "").upper()

    return dni_candidato if DNI_NIE_PATTERN.match(dni_candidato) else None


def _extraer_mes_nomina(page: fitz.Page) -> str | None:
    """Extrae 'AAAA-MM' del campo PERIODO (ej. 'MENS 01 JUN 26 a 30 JUN 26'), anclando en
    la cabecera PERIODO — no es una búsqueda de texto libre por toda la página.

    Devuelve None si el anclaje o el patrón esperado no aparecen en esta página en
    concreto: es una ayuda para sugerir un valor por defecto, no un dato crítico como el
    NIF o el DNI, así que quien llame debe estar preparado para recibir None y usar su
    propio valor por defecto.
    """
    words = page.get_text("words")

    periodo_x = next((x0 for x0, y0, x1, y1, w, *_ in words if w == PERIODO_HEADER), None)
    if periodo_x is None:
        return None

    header_y = min(y0 for x0, y0, x1, y1, w, *_ in words if w == PERIODO_HEADER)
    fila = _fila_bajo_cabecera(words, header_y, x_min=0, x_max=float("inf"))

    coincidencia = PERIODO_PATTERN.search(fila)
    if not coincidencia:
        return None

    mes_abreviado, anio_dos_digitos = coincidencia.groups()
    numero_mes = MES_ABREVIADO_A_NUMERO.get(mes_abreviado.upper())
    if numero_mes is None:
        return None

    # Asunción deliberada: el año de dos dígitos siempre es "20XX". Razonable en 2026 —
    # si este código sigue vivo en 2100, que quien lo lea se ría un poco de nosotros.
    anio_completo = 2000 + int(anio_dos_digitos)

    return f"{anio_completo:04d}-{numero_mes:02d}"


def extraer_mes_nomina(ruta_pdf: str, pagina: int) -> str | None:
    """Sugerencia de 'AAAA-MM' a partir del campo PERIODO de una página concreta del PDF
    (normalmente la primera nómina detectada, vía NominaDetectada.pagina_inicio).

    Devuelve None si no se puede determinar con confianza. Es una ayuda para precargar
    el formulario, nunca un dato crítico: el llamador debe caer a su propio valor por
    defecto si recibe None, sin fallar el resto de la subida por esto.
    """
    doc = fitz.open(ruta_pdf)
    if pagina < 0 or pagina >= len(doc):
        return None
    return _extraer_mes_nomina(doc[pagina])


def _buscar_nif_alternativo(doc: fitz.Document) -> str | None:
    for page in doc:
        coincidencia = NIF_GENERICO_PATTERN.search(page.get_text())
        if coincidencia:
            return coincidencia.group(1)
    return None


def detectar_nominas(ruta_pdf: str, nif_esperado: str) -> list[NominaDetectada]:
    """Detecta las nóminas de un PDF cuyo anclaje de empresa es 'NIF. <nif_esperado>'.

    `nif_esperado` viene de la empresa seleccionada al subir el PDF (app/main.py) — cada
    empresa del cliente tiene el suyo, nunca está fijo dentro del parser.
    """
    doc = fitz.open(ruta_pdf)
    patron_nif_esperado = re.compile(rf"NIF\.\s*{re.escape(nif_esperado)}")

    inicios = [i for i, page in enumerate(doc) if patron_nif_esperado.search(page.get_text())]
    if not inicios:
        raise SinNominasDetectadas(nif_esperado, _buscar_nif_alternativo(doc))

    nominas = []
    for idx, inicio in enumerate(inicios):
        fin = (inicios[idx + 1] - 1) if idx + 1 < len(inicios) else len(doc) - 1

        texto_bloque = "".join(doc[p].get_text() for p in range(inicio, fin + 1))
        if not CIERRE_PATTERN.search(texto_bloque):
            raise ParserError(
                f"La nómina en páginas {inicio}-{fin} no contiene el cierre esperado "
                "('Cotización adicional de solidaridad'); revisar manualmente"
            )

        nombre = _extraer_nombre_trabajador(doc[inicio])
        dni_nie = _extraer_dni_trabajador(doc[inicio])
        nominas.append(
            NominaDetectada(pagina_inicio=inicio, pagina_fin=fin, nombre_trabajador=nombre, dni_nie=dni_nie)
        )

    return nominas


def nombre_archivo_seguro(nombre: str) -> str:
    return nombre.replace(" ", "_").replace(",", "")


def extraer_paginas_bytes(reader: PdfReader, pagina_inicio: int, pagina_fin: int) -> bytes:
    """Devuelve, en memoria, un PDF sin cifrar con las páginas [pagina_inicio, pagina_fin].

    No escribe nada a disco: se usa para la vista previa, que no debe dejar
    ningún PDF sin cifrar residual en el sistema de archivos.
    """
    writer = PdfWriter()
    for p in range(pagina_inicio, pagina_fin + 1):
        writer.add_page(reader.pages[p])

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def separar_pdf(ruta_pdf: str, carpeta_salida: str, nif_esperado: str) -> list[str]:
    nominas = detectar_nominas(ruta_pdf, nif_esperado)
    reader = PdfReader(ruta_pdf)

    os.makedirs(carpeta_salida, exist_ok=True)
    rutas_generadas = []
    for i, nomina in enumerate(nominas, start=1):
        writer = PdfWriter()
        for p in range(nomina.pagina_inicio, nomina.pagina_fin + 1):
            writer.add_page(reader.pages[p])

        nombre_archivo = f"{i:02d}_{nombre_archivo_seguro(nomina.nombre_trabajador)}.pdf"
        ruta_salida = os.path.join(carpeta_salida, nombre_archivo)
        with open(ruta_salida, "wb") as f:
            writer.write(f)
        rutas_generadas.append(ruta_salida)

    return rutas_generadas
