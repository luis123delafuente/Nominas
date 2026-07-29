"""Validación de IBAN y BIC, reutilizable tanto para el IBAN de la ficha de empleado
como para las cuentas bancarias de empresa (app/db.py) y el generador SEPA (app/sepa.py).

El XSD oficial de pain.001.001.03 (ver schemas/pain.001.001.03.xsd) solo comprueba el
FORMATO del IBAN con una expresión regular (`[A-Z]{2}[0-9]{2}[a-zA-Z0-9]{1,30}`): un
IBAN con el formato correcto pero el dígito de control equivocado pasaría esa
validación sin problema y generaría un fichero que el banco rechazaría. Por eso este
módulo comprueba también el checksum ISO 7064 MOD97-10 explícitamente, antes de que
ese IBAN llegue al generador SEPA.
"""

import re

IBAN_FORMATO_PATTERN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]+$")
IBAN_LONGITUD_MINIMA = 15
IBAN_LONGITUD_MAXIMA = 34

# BIC/SWIFT: 4 letras de banco + 2 letras de país (ISO 3166 alfa-2) + 2 alfanuméricos
# de localidad + opcionalmente 3 alfanuméricos de sucursal (8 u 11 caracteres en total).
BIC_PATTERN = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def normalizar_iban(iban: str) -> str:
    return iban.strip().upper().replace(" ", "")


def normalizar_bic(bic: str) -> str:
    return bic.strip().upper().replace(" ", "")


def _checksum_mod97_valido(iban: str) -> bool:
    reordenado = iban[4:] + iban[:4]
    convertido = "".join(str(int(caracter, 36)) for caracter in reordenado)
    return int(convertido) % 97 == 1


def validar_iban(iban: str) -> None:
    """Lanza ValueError con un mensaje claro si `iban` (ya normalizado, ver
    `normalizar_iban`) no es válido: ni por formato ni por dígito de control."""
    if not IBAN_FORMATO_PATTERN.match(iban):
        raise ValueError(f"IBAN con formato inválido: '{iban}'")
    if not (IBAN_LONGITUD_MINIMA <= len(iban) <= IBAN_LONGITUD_MAXIMA):
        raise ValueError(f"IBAN con longitud inválida ({len(iban)} caracteres): '{iban}'")
    if not _checksum_mod97_valido(iban):
        raise ValueError(f"IBAN con dígito de control inválido — revisa que esté bien escrito: '{iban}'")


def validar_bic(bic: str) -> None:
    """Lanza ValueError con un mensaje claro si `bic` (ya normalizado, ver
    `normalizar_bic`) no tiene un formato de BIC/SWIFT válido (8 u 11 caracteres)."""
    if not BIC_PATTERN.match(bic):
        raise ValueError(f"BIC/SWIFT con formato inválido: '{bic}'")
