import io
import os
import re
from dataclasses import dataclass

import fitz
from pypdf import PdfReader, PdfWriter

NIF_EMPRESA_PATTERN = re.compile(r"NIF\.\s*B82827635")
CIERRE_PATTERN = re.compile(r"Cotización adicional de solidaridad", re.IGNORECASE)

TRABAJADOR_HEADER = "TRABAJADOR/A"
CATEGORIA_HEADER = "CATEGORIA"
ANTIGUEDAD_HEADER = "ANTIGUEDAD"
DNI_HEADER = "D.N.I."

DNI_NIE_PATTERN = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")


class ParserError(Exception):
    """Anclajes esperados no encontrados: requiere revisión manual."""


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


def detectar_nominas(ruta_pdf: str) -> list[NominaDetectada]:
    doc = fitz.open(ruta_pdf)

    inicios = [i for i, page in enumerate(doc) if NIF_EMPRESA_PATTERN.search(page.get_text())]
    if not inicios:
        raise ParserError(f"No se encontró ningún anclaje 'NIF. B82827635' en {ruta_pdf}")

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


def separar_pdf(ruta_pdf: str, carpeta_salida: str) -> list[str]:
    nominas = detectar_nominas(ruta_pdf)
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
