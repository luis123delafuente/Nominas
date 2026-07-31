import io
import os
import re
import unicodedata
from dataclasses import dataclass

import fitz
from pypdf import PdfReader, PdfWriter
from rapidfuzz import fuzz

from app.ocr import ocr_pagina
from app.sepa import ImporteInvalido, parsear_importe_a_centimos

# Rótulo del NIF/CIF de empresa tal como lo imprime la gestoría. No es estable entre
# plantillas: 'NIF.', 'CIF', 'N.I.F.', 'C.I.F.', con ':', '.' o '-' como separador
# (con o sin espacios a ambos lados). El NIF/CIF concreto tras el rótulo sí es exacto.
NIF_CIF_LABEL = r"\b(?:N\.?I\.?F\.?|C\.?I\.?F\.?)\s*[:.\-]?\s*"

# Patrón genérico para detectar CUALQUIER NIF/CIF con formato reconocible en el PDF,
# aunque no sea el esperado — se usa solo para dar una pista útil en el mensaje de error
# ("parece que has subido el PDF de otra empresa").
NIF_GENERICO_PATTERN = re.compile(rf"{NIF_CIF_LABEL}([A-Z0-9]{{8,9}})")

TRABAJADOR_HEADER = "TRABAJADOR/A"
CATEGORIA_HEADER = "CATEGORIA"
ANTIGUEDAD_HEADER = "ANTIGUEDAD"
DNI_HEADER = "D.N.I."
PERIODO_HEADER = "PERIODO"
LIQUIDO_HEADER_1 = "LIQUIDO"
LIQUIDO_HEADER_2 = "PERCIBIR"

DNI_NIE_PATTERN = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")

# Ej.: "MENS 01 JUN 26 a 30 JUN 26" -> captura mes abreviado y año de 2 dígitos del inicio.
PERIODO_PATTERN = re.compile(r"\bMENS\s+\d{1,2}\s+([A-Z]{3})\s+(\d{2})\b")
MES_ABREVIADO_A_NUMERO = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


def _quitar_tildes(texto: str) -> str:
    """Elimina las tildes sin tocar el resto: 'Cotización' -> 'Cotizacion'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _normalizar_texto(texto: str) -> str:
    """Mayúsculas y sin tildes, para comparar anclas y cierres de forma robusta ante
    los pequeños errores del OCR (tildes que desaparecen, etc.)."""
    return _quitar_tildes(texto.upper())


CIERRE = "Cotización adicional de solidaridad"
CIERRE_NORMALIZADO = _normalizar_texto(CIERRE)


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
    liquido_a_percibir: str | None  # None si no se pudo autoextraer con confianza — cae al campo manual


# --- Emparejamiento tolerante de cabeceras (resistente a artefactos de OCR) ---------
#
# El OCR de una página escaneada no es idéntico a la capa de texto de un PDF editable:
# puede leer 'TRABAJADOR/A' como 'TRABAJADORIA' o 'D.N.I.' como 'D.N.1.'. Estas
# funciones comparan las cabeceras de forma que esas variantes sigan coincidiendo,
# sin falsear los datos extraídos (la normalización solo se aplica a la cabecera,
# nunca al contenido).


def _normalizar_cabecera(texto: str) -> str:
    """Forma comparable de una cabecera: mayúsculas, sin tildes, sin puntuación
    ('D.N.I.' -> 'DNI') y con corrección de dígitos que el OCR confunde con letras
    ('D.N.1.' -> 'DNI'). Ninguna cabecera que buscamos contiene dígitos legítimos,
    así que mapear 1->I y 0->O dentro de esta comparación es seguro."""
    texto = _quitar_tildes(texto.upper())
    texto = "".join(c for c in texto if c.isalnum())
    return texto.translate(str.maketrans("10", "IO"))


def _coincide_cabecera(palabra: str, cabecera: str) -> bool:
    """¿Coincide una palabra con la cabecera esperada? Exigencia alta para no
    confundir datos con cabeceras: coincidencia exacta tras normalizar, similitud
    ≥ 85% (rapidfuzz) para variantes ligeras del OCR, o que la cabecera aparezca como
    subcadena casi completa (≥ 92%) para cortes del OCR tipo 'D.N./' -> 'D.N.I.'."""
    a = _normalizar_cabecera(palabra)
    b = _normalizar_cabecera(cabecera)
    if not a or not b:
        return False
    if a == b:
        return True
    if fuzz.ratio(a, b) >= 85:
        return True
    # Cabeceras truncadas por el OCR (ej. 'D.N./' -> 'D.N.I.'): aceptamos que la
    # palabra sea casi subcadena de la cabecera, pero solo si cubre al menos el 60%
    # de su longitud — así palabras sueltas ('D', 'AT', '1') no dan falsos positivos.
    cobertura_minima = max(2, int(len(b) * 0.6))
    return len(a) >= cobertura_minima and fuzz.partial_ratio(a, b) >= 92


def _palabra_contiene_cabecera(palabra: str, cabecera: str) -> bool:
    """¿Una palabra o una de sus palabras internas coincide con la cabecera?

    Necesario porque el OCR a veces une en una sola línea lo que en el PDF con texto
    son palabras separadas: 'LIQUIDO A PERCIBIR' es una única caja de OCR.
    """
    if _coincide_cabecera(palabra, cabecera):
        return True
    return any(_coincide_cabecera(t, cabecera) for t in palabra.split())


def _encontrar_cabecera(words, cabecera: str):
    """Devuelve la primera palabra que coincide con la cabecera como
    `(x0, y0, x1, y1, texto)`, o None si no aparece."""
    for x0, y0, x1, y1, w, *_ in words:
        if _coincide_cabecera(w, cabecera):
            return x0, y0, x1, y1, w
    return None


# --- Extracción de datos -------------------------------------------------------------


def _fila_bajo_cabecera(words, header_y: float, x_min: float, x_max: float) -> str:
    candidatos = [(x0, y0, w) for x0, y0, x1, y1, w, *_ in words if x_min <= x0 < x_max and y0 > header_y + 2]
    if not candidatos:
        return ""

    fila_y = min(y0 for _, y0, _ in candidatos)
    fila_datos = sorted((x0, w) for x0, y0, w in candidatos if abs(y0 - fila_y) < 3)
    return " ".join(w for _, w in fila_datos).strip()


def _extraer_nombre_trabajador(words, numero_pagina: int) -> str:
    trabajador = _encontrar_cabecera(words, TRABAJADOR_HEADER)
    categoria = _encontrar_cabecera(words, CATEGORIA_HEADER)
    if trabajador is None or categoria is None:
        raise ParserError(
            f"No se encontraron las cabeceras {TRABAJADOR_HEADER}/{CATEGORIA_HEADER} "
            f"en la página {numero_pagina}"
        )

    trabajador_x, header_y, *_ = trabajador
    categoria_x = categoria[0]
    limite_derecho = (trabajador_x + categoria_x) / 2

    nombre = _fila_bajo_cabecera(words, header_y, x_min=0, x_max=limite_derecho)
    if not nombre:
        raise ParserError(f"No se encontró la fila de datos del trabajador en la página {numero_pagina}")
    return nombre


def _extraer_dni_trabajador(words) -> str | None:
    """Devuelve el D.N.I./N.I.E. del trabajador, o None si no se pudo extraer con formato reconocible.

    A diferencia del nombre, la ausencia de un D.N.I. válido en una nómina concreta
    no es un error fatal del parseo: se deja que el matcher decida cómo tratarlo
    (normalmente cayendo a un emparejamiento por nombre para ese caso puntual).
    """
    antiguedad = _encontrar_cabecera(words, ANTIGUEDAD_HEADER)
    dni = _encontrar_cabecera(words, DNI_HEADER)
    if antiguedad is None or dni is None:
        return None

    antiguedad_x = antiguedad[0]
    dni_x = dni[0]
    header_y = dni[1]

    limite_izquierdo = (antiguedad_x + dni_x) / 2
    dni_candidato = _fila_bajo_cabecera(words, header_y, x_min=limite_izquierdo, x_max=float("inf"))
    dni_candidato = dni_candidato.replace(" ", "").upper()

    return dni_candidato if DNI_NIE_PATTERN.match(dni_candidato) else None


def _buscar_fila_con_cabeceras(words, cabecera_a: str, cabecera_b: str):
    """Devuelve `(x0_fila, y0_fila, x1_derecha)` de la primera fila que contiene las dos
    cabeceras en la misma fila visual.

    Cubre tanto el PDF con texto (cabeceras en palabras separadas: 'LIQUIDO' y
    'A PERCIBIR') como el escaneado (OCR que las une en una sola caja de texto).
    """
    for x0, y0, x1, y1, w, *_ in words:
        if not _palabra_contiene_cabecera(w, cabecera_a):
            continue
        x1_derecha = max(
            (
                x1b
                for x0b, y0b, x1b, y1b, wb, *_ in words
                if abs(y0b - y0) < 3 and _palabra_contiene_cabecera(wb, cabecera_b)
            ),
            default=None,
        )
        if x1_derecha is not None:
            return x0, y0, x1_derecha
    return None


def _extraer_liquido_a_percibir(words) -> str | None:
    """Devuelve el importe bajo la cabecera 'LIQUIDO A PERCIBIR', o None si no se pudo
    autoextraer con confianza (anclaje no encontrado o texto que no es un importe con
    formato válido).

    Igual que el D.N.I., la ausencia de este dato en una nómina concreta no es un error
    fatal del parseo: es una ayuda para precargar el campo manual ya existente en la
    pantalla de revisión (Fase 2), nunca un dato crítico que bloquee la subida. La
    validación de formato reutiliza `parsear_importe_a_centimos` (la misma que usa el
    generador SEPA) para no aceptar en silencio un texto que "parece" un importe pero
    no lo es — así el nivel de confianza (autoextraído vs. manual) es honesto.
    """
    fila = _buscar_fila_con_cabeceras(words, LIQUIDO_HEADER_1, LIQUIDO_HEADER_2)
    if fila is None:
        return None
    liquido_x, header_y, percibir_x1 = fila

    importe_candidato = _fila_bajo_cabecera(words, header_y, x_min=liquido_x, x_max=percibir_x1)
    if not importe_candidato:
        return None

    try:
        parsear_importe_a_centimos(importe_candidato)
    except ImporteInvalido:
        return None

    return importe_candidato


def _extraer_mes_nomina(words) -> str | None:
    """Extrae 'AAAA-MM' del campo PERIODO (ej. 'MENS 01 JUN 26 a 30 JUN 26'), anclando en
    la cabecera PERIODO — no es una búsqueda de texto libre por toda la página.

    Devuelve None si el anclaje o el patrón esperado no aparecen en esta página en
    concreto: es una ayuda para sugerir un valor por defecto, no un dato crítico como el
    NIF o el DNI, así que quien llame debe estar preparado para recibir None y usar su
    propio valor por defecto.
    """
    periodo = _encontrar_cabecera(words, PERIODO_HEADER)
    if periodo is None:
        return None

    header_y = periodo[1]
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


# --- Contenido de una página (capa de texto o OCR) -----------------------------------


def _contenido_pagina(ruta_pdf: str, page: fitz.Page) -> tuple[list, str]:
    """Devuelve `(words, texto)` de una página, leyendo la capa de texto si existe o
    ejecutando OCR local (macOS Vision) si la página es un escaneado sin texto."""
    texto = page.get_text()
    if texto.strip():
        return page.get_text("words"), texto

    palabras = ocr_pagina(ruta_pdf, page.number, page)
    return palabras, "\n".join(w[4] for w in palabras)


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
    palabras, _ = _contenido_pagina(ruta_pdf, doc[pagina])
    return _extraer_mes_nomina(palabras)


def _buscar_nif_alternativo(paginas: list) -> str | None:
    for _, texto in paginas:
        coincidencia = NIF_GENERICO_PATTERN.search(texto)
        if coincidencia:
            return coincidencia.group(1)
    return None


def detectar_nominas(ruta_pdf: str, nif_esperado: str) -> list[NominaDetectada]:
    """Detecta las nóminas de un PDF cuyo anclaje de empresa es 'NIF. <nif_esperado>'.

    `nif_esperado` viene de la empresa seleccionada al subir el PDF (app/main.py) — cada
    empresa del cliente tiene el suyo, nunca está fijo dentro del parser.

    Funciona tanto con PDFs con capa de texto como con PDFs escaneados: para estos
    últimos se ejecuta OCR local con macOS Vision (app/ocr.py).
    """
    doc = fitz.open(ruta_pdf)
    paginas = [_contenido_pagina(ruta_pdf, page) for page in doc]

    # El anclaje de empresa es el NIF/CIF que la gestoría imprime en cada nómina
    # ('NIF. B82827635'), pero el rótulo no es estable entre gestorías/plantillas:
    # puede aparecer como 'CIF.', 'N.I.F.', 'C.I.F.' o con ':' o '-' de separador.
    # El CIF concreto tras el rótulo sí es exacto, así que no hay riesgo de falso
    # positivo al aceptar todas las variantes del rótulo.
    patron_nif_esperado = re.compile(rf"{NIF_CIF_LABEL}{re.escape(nif_esperado)}")

    inicios = [i for i, (_, texto) in enumerate(paginas) if patron_nif_esperado.search(texto)]
    if not inicios:
        raise SinNominasDetectadas(nif_esperado, _buscar_nif_alternativo(paginas))

    nominas = []
    for idx, inicio in enumerate(inicios):
        fin = (inicios[idx + 1] - 1) if idx + 1 < len(inicios) else len(doc) - 1

        texto_bloque = "".join(paginas[p][1] for p in range(inicio, fin + 1))
        if CIERRE_NORMALIZADO not in _normalizar_texto(texto_bloque):
            raise ParserError(
                f"La nómina en páginas {inicio}-{fin} no contiene el cierre esperado "
                f"('{CIERRE}'); revisar manualmente"
            )

        words = paginas[inicio][0]
        nombre = _extraer_nombre_trabajador(words, inicio)
        dni_nie = _extraer_dni_trabajador(words)
        liquido_a_percibir = _extraer_liquido_a_percibir(words)
        nominas.append(
            NominaDetectada(
                pagina_inicio=inicio,
                pagina_fin=fin,
                nombre_trabajador=nombre,
                dni_nie=dni_nie,
                liquido_a_percibir=liquido_a_percibir,
            )
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
