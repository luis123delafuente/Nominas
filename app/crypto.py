import os
from collections.abc import Iterable

from pypdf import PdfReader, PdfWriter


def cifrar_paginas(reader: PdfReader, paginas: Iterable[int], ruta_salida: str, password: str) -> None:
    """Cifra con AES-256 las `paginas` (índices 0-based) de `reader` y escribe el resultado en `ruta_salida`.

    `password` debe venir ya normalizada por el llamador (DNI/NIE en mayúsculas y sin espacios,
    tal como aparece en la nómina): esta función no valida ni transforma la contraseña.
    """
    writer = PdfWriter()
    for p in paginas:
        writer.add_page(reader.pages[p])

    writer.encrypt(user_password=password, algorithm="AES-256")

    os.makedirs(os.path.dirname(ruta_salida) or ".", exist_ok=True)
    with open(ruta_salida, "wb") as f:
        writer.write(f)


def cifrar_pdf(ruta_entrada: str, ruta_salida: str, password: str) -> None:
    reader = PdfReader(ruta_entrada)
    cifrar_paginas(reader, range(len(reader.pages)), ruta_salida, password)
