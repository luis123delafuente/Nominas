from datetime import date
from pathlib import Path

import pytest
import xmlschema

from app.config import Configuracion, GeneracionBloqueadaPorModoPrueba
from app.sepa import ImporteInvalido, PagoSepa, generar_fichero_sepa, parsear_importe_a_centimos

XSD_PAIN_001 = Path(__file__).resolve().parent.parent / "schemas" / "pain.001.001.03.xsd"

IBAN_EMPRESA = "ES9121000418450200051332"
BIC_EMPRESA = "CAIXESBBXXX"
IBAN_EMPLEADO_1 = "ES7620770024003102575766"
IBAN_EMPLEADO_2 = "DE89370400440532013000"


def _config(modo_envio="produccion"):
    return Configuracion(modo_envio=modo_envio, email_prueba="prueba@example.com")


def _pago(empleado_id=1, iban=IBAN_EMPLEADO_1, importe_centimos=157284, nombre="Nicolas Alcalde Lasaosa"):
    return PagoSepa(
        empleado_id=empleado_id,
        nombre=nombre,
        iban=iban,
        importe_centimos=importe_centimos,
        concepto="Nomina 2026-06",
        endtoend_id=f"NOM-2026-06-{empleado_id}",
    )


# --- parsear_importe_a_centimos ---------------------------------------------------


@pytest.mark.parametrize(
    "texto,centimos_esperados",
    [
        ("1.572,84", 157284),
        ("1572,84", 157284),
        ("1572.84", 157284),
        ("1572", 157200),
        ("  1.572,84  ", 157284),
    ],
)
def test_parsear_importe_formatos_validos(texto, centimos_esperados):
    assert parsear_importe_a_centimos(texto) == centimos_esperados


@pytest.mark.parametrize("texto", ["", "   ", "no es un numero", "-100", "0", "1572,845"])
def test_parsear_importe_formatos_invalidos_se_rechazan(texto):
    with pytest.raises(ImporteInvalido):
        parsear_importe_a_centimos(texto)


# --- generar_fichero_sepa: bloqueo en modo prueba ----------------------------------


def test_modo_prueba_bloquea_la_generacion_del_fichero_sepa(tmp_path):
    ruta_salida = tmp_path / "sepa.xml"

    with pytest.raises(GeneracionBloqueadaPorModoPrueba):
        generar_fichero_sepa(
            _config(modo_envio="prueba"),
            "MEDIFORM PLUS S.L.",
            IBAN_EMPRESA,
            BIC_EMPRESA,
            "2026-06",
            [_pago()],
            str(ruta_salida),
        )

    assert not ruta_salida.exists()  # bloqueado de forma verificable: ni siquiera se crea


def test_modo_produccion_genera_el_fichero(tmp_path):
    ruta_salida = tmp_path / "sepa.xml"

    generar_fichero_sepa(
        _config(modo_envio="produccion"),
        "MEDIFORM PLUS S.L.",
        IBAN_EMPRESA,
        BIC_EMPRESA,
        "2026-06",
        [_pago()],
        str(ruta_salida),
    )

    assert ruta_salida.exists()


# --- generar_fichero_sepa: validación de IBAN con checksum incorrecto -------------


def test_iban_de_empresa_con_checksum_invalido_aborta_sin_generar_nada(tmp_path):
    ruta_salida = tmp_path / "sepa.xml"

    with pytest.raises(ValueError, match="dígito de control"):
        generar_fichero_sepa(
            _config(),
            "MEDIFORM PLUS S.L.",
            "ES9121000418450200051333",  # mismo IBAN válido con el último dígito cambiado
            BIC_EMPRESA,
            "2026-06",
            [_pago()],
            str(ruta_salida),
        )

    assert not ruta_salida.exists()


def test_iban_de_empleado_con_checksum_invalido_aborta_sin_generar_nada(tmp_path):
    ruta_salida = tmp_path / "sepa.xml"
    pago_invalido = _pago(iban="ES7620770024003102575767")  # checksum roto a propósito

    with pytest.raises(ValueError, match="dígito de control"):
        generar_fichero_sepa(
            _config(),
            "MEDIFORM PLUS S.L.",
            IBAN_EMPRESA,
            BIC_EMPRESA,
            "2026-06",
            [pago_invalido],
            str(ruta_salida),
        )

    assert not ruta_salida.exists()


# --- generar_fichero_sepa: XML resultante -------------------------------------------


def test_fichero_generado_valida_contra_el_xsd_oficial(tmp_path):
    """No basta con que `sepa.export()` no lance una excepción: se revalida el XML
    de forma independiente contra la copia local del XSD oficial pain.001.001.03."""
    ruta_salida = tmp_path / "sepa.xml"

    xml_bytes = generar_fichero_sepa(
        _config(),
        "MEDIFORM PLUS S.L.",
        IBAN_EMPRESA,
        BIC_EMPRESA,
        "2026-06",
        [_pago(1, IBAN_EMPLEADO_1, 157284, "Nicolas Alcalde Lasaosa"), _pago(2, IBAN_EMPLEADO_2, 98050, "Otro Empleado")],
        str(ruta_salida),
        fecha_ejecucion=date(2026, 7, 30),
    )

    esquema = xmlschema.XMLSchema(str(XSD_PAIN_001))
    esquema.validate(xml_bytes.decode("utf-8"))  # lanza si no es válido

    assert ruta_salida.read_bytes() == xml_bytes


def test_fichero_generado_contiene_los_importes_y_ibans_correctos(tmp_path):
    ruta_salida = tmp_path / "sepa.xml"

    xml_bytes = generar_fichero_sepa(
        _config(),
        "MEDIFORM PLUS S.L.",
        IBAN_EMPRESA,
        BIC_EMPRESA,
        "2026-06",
        [_pago(1, IBAN_EMPLEADO_1, 157284, "Nicolas Alcalde Lasaosa")],
        str(ruta_salida),
        fecha_ejecucion=date(2026, 7, 30),
    )
    xml_texto = xml_bytes.decode("utf-8")

    assert IBAN_EMPRESA in xml_texto
    assert IBAN_EMPLEADO_1 in xml_texto
    assert "1572.84" in xml_texto  # InstdAmt y CtrlSum, en formato decimal con punto
    assert "<NbOfTxs>1</NbOfTxs>" in xml_texto


def test_sin_pagos_lanza_error_claro(tmp_path):
    ruta_salida = tmp_path / "sepa.xml"

    with pytest.raises(ValueError, match="ningún pago"):
        generar_fichero_sepa(
            _config(),
            "MEDIFORM PLUS S.L.",
            IBAN_EMPRESA,
            BIC_EMPRESA,
            "2026-06",
            [],
            str(ruta_salida),
        )
