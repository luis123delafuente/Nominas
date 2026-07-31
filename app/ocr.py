"""OCR local para páginas escaneadas mediante el framework Vision de macOS.

La gestoría a veces envía el PDF mensual como escaneado, sin capa de texto. PyMuPDF
solo puede leer texto incrustado, así que para esas páginas se ejecuta OCR con el
framework nativo de macOS (Vision, vía `ocrmac`): gratis, 100% local y con buena
calidad en español.

El resultado se devuelve como pseudo-palabras con coordenadas en puntos PDF
(origen arriba-izquierda), el mismo formato que `Page.get_text("words")`, para que
el resto del parser no distinga entre texto incrustado y OCR.
"""

import hashlib
import json
import os
from pathlib import Path

import fitz
from ocrmac import ocrmac
from PIL import Image

# 200 DPI: suficiente para las cabeceras y cifras de la nómina (verificado con el PDF
# escaneado real de julio 2026). A más DPI tarda más sin ganar precisión relevante.
DPI_OCR = 200

_CACHE: dict[tuple, list] = {}
_HASH_POR_ARCHIVO: dict[tuple, str] = {}

# La caché en disco persiste entre reinicios de la app: el PDF mensual escaneado tarda
# ~20 s en OCRearse, así que no hay que volver a pagarlos cada vez que se sube el mismo
# archivo (o se reinicia la aplicación).
OCR_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "ocr_cache"


def _hash_pdf(ruta_pdf: str) -> str:
    """SHA-256 del contenido del PDF, memoizado por (ruta, tamaño, mtime).

    Se memoiza porque `detectar_nominas` recorre todas las páginas llamando a
    `ocr_pagina` por página, y no queremos releer/hashear el archivo 29 veces.
    """
    clave_archivo = (ruta_pdf, os.path.getsize(ruta_pdf), os.path.getmtime(ruta_pdf))
    digest = _HASH_POR_ARCHIVO.get(clave_archivo)
    if digest is None:
        with open(ruta_pdf, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        _HASH_POR_ARCHIVO[clave_archivo] = digest
    return digest


def ocr_pagina(ruta_pdf: str, pagina: int, page: fitz.Page) -> list:
    """Devuelve las pseudo-palabras `(x0, y0, x1, y1, texto)` de una página escaneada.

    Resultados cacheados en memoria por (ruta, tamaño, mtime, página) y en disco por
    el hash del contenido: dentro de un mismo flujo de subida no se repite el OCR, y
    entre reinicios de la app el mismo PDF (aunque se re-suba con otro mtime) se sirve
    desde disco. Un PDF distinto genera una clave nueva y se OCReará de nuevo.
    """
    clave = None
    if ruta_pdf and os.path.isfile(ruta_pdf):
        clave = (ruta_pdf, os.path.getsize(ruta_pdf), os.path.getmtime(ruta_pdf), pagina)
        if clave in _CACHE:
            return _CACHE[clave]

        ruta_disco = OCR_CACHE_DIR / f"{_hash_pdf(ruta_pdf)}_{pagina}.json"
        if ruta_disco.exists():
            palabras = [tuple(w) for w in json.loads(ruta_disco.read_text(encoding="utf-8"))]
            _CACHE[clave] = palabras
            return palabras

    pix = page.get_pixmap(dpi=DPI_OCR)
    imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    resultado = ocrmac.OCR(
        imagen,
        language_preference=["es-ES"],
        recognition_level="accurate",
    ).recognize()

    palabras = []
    ancho, alto = page.rect.width, page.rect.height
    for texto, _confianza, (x, y, w, h) in resultado:
        texto = texto.strip()
        if not texto:
            continue
        # Vision devuelve la caja normalizada (0-1) con el origen abajo-izquierda;
        # se convierte a puntos PDF con el origen arriba-izquierda.
        x0 = x * ancho
        y0 = alto - (y + h) * alto
        x1 = (x + w) * ancho
        y1 = alto - y * alto
        palabras.append((x0, y0, x1, y1, texto))

    if clave:
        _CACHE[clave] = palabras
        OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ruta_disco.write_text(json.dumps(palabras), encoding="utf-8")
    return palabras


def limpiar_cache() -> None:
    _CACHE.clear()
