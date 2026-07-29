"""Generador del fichero de transferencias SEPA (ISO 20022 pain.001.001.03) a partir de
los "líquidos a percibir" confirmados a mano en la pantalla de revisión.

Decisiones de diseño:

- Se usa la librería `sepaxml` (MIT, sin coste, 100% local) en vez de construir el XML
  a mano. pain.001.001.03 tiene una estructura profunda con reglas de anidamiento no
  triviales (PmtInf, CdtTrfTxInf, agrupación en lote, checksums de control...); una
  librería madura y usada en producción por otros proyectos SEPA reduce mucho el
  riesgo de generar un XML que "parece" correcto pero no lo es. `sepaxml` trae además
  el XSD oficial embebido y valida el resultado contra él en `export(validate=True)`
  — lo dejamos siempre activado, así que un error de validación aborta la generación
  en vez de escribir un fichero inválido a disco.
- Además de esa autovalidación, este proyecto guarda su propia copia del XSD oficial
  en `schemas/pain.001.001.03.xsd` (idéntica a la que trae la librería) y la usa en un
  test independiente (`tests/test_sepa.py`), para no depender solo de que la librería
  "no lance una excepción" como prueba de que el fichero es válido.
- El XSD oficial solo valida el FORMATO del IBAN (una expresión regular), no el dígito
  de control. Por eso aquí se llama explícitamente a `validar_iban`/`validar_bic`
  (checksum ISO 7064 mod-97 incluido) antes de construir el XML, tanto para la cuenta
  de la empresa como para el IBAN de cada empleado.
- El BIC del empleado no se pide ni se incluye en el fichero: desde el Reglamento (UE)
  260/2012 el BIC ya no es obligatorio en transferencias SEPA dentro de la UE/EEE si
  se conoce el IBAN, que es el único dato bancario que se guarda en la ficha de cada
  trabajador (menos dato sensible que cifrar y validar por empleado).
- Un único lote (PmtInf, `batch=True`): todos los pagos de la misma empresa y mes
  comparten una sola fecha de ejecución.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sepaxml import SepaTransfer

from app.config import Configuracion, asegurar_generacion_permitida
from app.validaciones_bancarias import normalizar_bic, normalizar_iban, validar_bic, validar_iban

IMPORTE_PATTERN = re.compile(r"^\d{1,3}(\.\d{3})*(,\d{1,2})?$|^\d+([.,]\d{1,2})?$")


class ImporteInvalido(Exception):
    """El texto de 'líquido a percibir' introducido en la revisión no es un importe válido."""


@dataclass
class PagoSepa:
    empleado_id: int
    nombre: str
    iban: str
    importe_centimos: int
    concepto: str
    endtoend_id: str


def parsear_importe_a_centimos(texto: str) -> int:
    """Convierte un importe escrito a mano en la revisión (admite '1.572,84', '1572,84'
    o '1572.84') a céntimos (entero), que es la unidad que espera `sepaxml`.

    Se rechaza cualquier texto que no sea un importe positivo reconocible: en un
    fichero que mueve dinero real no se debe adivinar un formato ambiguo.
    """
    texto_limpio = texto.strip().replace(" ", "")
    if not texto_limpio:
        raise ImporteInvalido("El importe no puede estar vacío.")
    if not IMPORTE_PATTERN.match(texto_limpio):
        raise ImporteInvalido(f"Importe con formato irreconocible: '{texto}'")

    if "," in texto_limpio and "." in texto_limpio:
        texto_normalizado = texto_limpio.replace(".", "").replace(",", ".")
    elif "," in texto_limpio:
        texto_normalizado = texto_limpio.replace(",", ".")
    else:
        texto_normalizado = texto_limpio

    try:
        importe = Decimal(texto_normalizado)
    except InvalidOperation:
        raise ImporteInvalido(f"Importe con formato irreconocible: '{texto}'") from None

    if importe <= 0:
        raise ImporteInvalido(f"El importe debe ser mayor que cero: '{texto}'")

    return int(importe * 100)


def generar_fichero_sepa(
    config: Configuracion,
    nombre_empresa: str,
    iban_empresa: str,
    bic_empresa: str,
    mes_nomina: str,
    pagos: list[PagoSepa],
    ruta_salida: str,
    fecha_ejecucion: date | None = None,
) -> bytes:
    """Genera el fichero SEPA (pain.001.001.03) para `pagos` y lo escribe en `ruta_salida`.
    Devuelve también el XML en bytes, para poder ofrecerlo como descarga sin releer el disco.

    Primera línea: `asegurar_generacion_permitida` — en modo prueba lanza
    `GeneracionBloqueadaPorModoPrueba` antes de validar nada más y antes de tocar el
    disco. Nunca debe poder existir un fichero SEPA real generado durante pruebas.
    """
    asegurar_generacion_permitida(config, "fichero SEPA")

    if not pagos:
        raise ValueError("No hay ningún pago que incluir en el fichero SEPA.")

    iban_empresa_normalizado = normalizar_iban(iban_empresa)
    validar_iban(iban_empresa_normalizado)
    bic_empresa_normalizado = normalizar_bic(bic_empresa)
    validar_bic(bic_empresa_normalizado)

    sepa = SepaTransfer(
        {
            "name": nombre_empresa,
            "IBAN": iban_empresa_normalizado,
            "BIC": bic_empresa_normalizado,
            "batch": True,
            "currency": "EUR",
        },
        clean=True,
    )

    fecha = fecha_ejecucion or date.today()
    for pago in pagos:
        iban_empleado_normalizado = normalizar_iban(pago.iban)
        validar_iban(iban_empleado_normalizado)
        sepa.add_payment(
            {
                "name": pago.nombre,
                "IBAN": iban_empleado_normalizado,
                "amount": pago.importe_centimos,
                "description": pago.concepto,
                "execution_date": fecha,
                "endtoend_id": pago.endtoend_id,
            }
        )

    xml_bytes = sepa.export(validate=True, pretty_print=True)

    ruta = Path(ruta_salida)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(xml_bytes)

    return xml_bytes
