import os
from dataclasses import replace

import pytest
import xmlschema
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import (
    NIF_MEDIFORM_PLUS,
    NOMBRE_MEDIFORM_PLUS,
    actualizar_iban_empleado,
    crear_cuenta_bancaria,
    crear_empleado,
    get_connection,
    init_db,
)

PDF_EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "entrada", "NOMINAS_062026.pdf")
XSD_PAIN_001 = os.path.join(os.path.dirname(__file__), "..", "schemas", "pain.001.001.03.xsd")

pytestmark = pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO),
    reason="Requiere el PDF de ejemplo real en entrada/NOMINAS_062026.pdf (no versionado por ser dato sensible)",
)

DNI_EMPLEADO = "02349419S"
NOMBRE_EMPLEADO = "Nicolás Alcalde Lasaosa"
IBAN_EMPLEADO = "ES7620770024003102575766"
IBAN_EMPRESA = "ES9121000418450200051332"
BIC_EMPRESA = "CAIXESBBXXX"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """BD, carpeta de entrada y clave de cifrado temporales, para no tocar nada real."""
    ruta_db = tmp_path / "test_nominas.db"
    ruta_clave = tmp_path / "clave_cifrado.key"
    monkeypatch.setattr(main_module, "get_connection", lambda db_path=ruta_db: get_connection(db_path))
    monkeypatch.setattr(main_module, "ENTRADA_DIR", tmp_path / "entrada")
    monkeypatch.setattr(main_module, "SALIDA_DIR", tmp_path / "salida")
    monkeypatch.setattr("app.crypto_campos.RUTA_CLAVE_POR_DEFECTO", ruta_clave)
    monkeypatch.setattr("app.config.RUTA_CONFIG_LOCAL", tmp_path / "config_no_existe.py")  # modo prueba por defecto

    conn = get_connection(ruta_db)
    empresa_id = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", (NOMBRE_MEDIFORM_PLUS, NIF_MEDIFORM_PLUS)
    ).lastrowid
    conn.commit()
    empleado_id = crear_empleado(conn, NOMBRE_EMPLEADO, DNI_EMPLEADO, "nicolas@example.com", "2025-01-01")
    actualizar_iban_empleado(conn, empleado_id, IBAN_EMPLEADO)
    cuenta_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_EMPRESA, BIC_EMPRESA, alias="Cuenta nómina")
    conn.close()

    with TestClient(main_module.app) as test_client:
        yield test_client, empleado_id, empresa_id, cuenta_id


def _subir_pdf_de_ejemplo(test_client, empresa_id):
    with open(PDF_EJEMPLO, "rb") as f:
        return test_client.post(
            "/subir",
            files={"pdf": ("NOMINAS_062026.pdf", f, "application/pdf")},
            data={"empresa_id": empresa_id},
            follow_redirects=True,
        )


def _activar_modo_produccion(monkeypatch, tmp_path):
    ruta_config = tmp_path / "config.local.py"
    ruta_config.write_text('MODO_ENVIO = "produccion"\n')
    monkeypatch.setattr("app.config.RUTA_CONFIG_LOCAL", ruta_config)


def test_revisar_muestra_la_cuenta_predeterminada_preseleccionada(client):
    test_client, _, empresa_id, cuenta_id = client

    respuesta = _subir_pdf_de_ejemplo(test_client, empresa_id)

    assert respuesta.status_code == 200
    assert f'value="{cuenta_id}" selected' in respuesta.text
    assert "IBAN" in respuesta.text  # columna de la sección SEPA


def test_generar_sepa_en_modo_prueba_no_genera_fichero(client, tmp_path):
    test_client, empleado_id, empresa_id, cuenta_id = client
    _subir_pdf_de_ejemplo(test_client, empresa_id)

    respuesta = test_client.post(
        "/revisar/generar_sepa",
        data={"cuenta_id": str(cuenta_id), "sepa_incluir": ["1"], "sepa_liquido_1": "1.572,84"},
    )

    assert respuesta.status_code == 400
    assert "MODO_ENVIO" in respuesta.text or "produccion" in respuesta.text
    ruta_salida = tmp_path / "salida" / NIF_MEDIFORM_PLUS / "2026-06" / "SEPA_2026-06.xml"
    assert not ruta_salida.exists()


def test_generar_sepa_en_modo_produccion_genera_xml_valido(client, tmp_path, monkeypatch):
    test_client, empleado_id, empresa_id, cuenta_id = client
    _activar_modo_produccion(monkeypatch, tmp_path)
    _subir_pdf_de_ejemplo(test_client, empresa_id)

    respuesta = test_client.post(
        "/revisar/generar_sepa",
        data={"cuenta_id": str(cuenta_id), "sepa_incluir": ["1"], "sepa_liquido_1": "1.572,84"},
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("application/xml")
    assert IBAN_EMPLEADO in respuesta.text
    assert IBAN_EMPRESA in respuesta.text

    esquema = xmlschema.XMLSchema(XSD_PAIN_001)
    esquema.validate(respuesta.text)  # lanza si no es válido

    ruta_salida = tmp_path / "salida" / NIF_MEDIFORM_PLUS / "2026-06" / "SEPA_2026-06.xml"
    assert ruta_salida.exists()


def test_generar_sepa_sin_liquido_a_percibir_da_error_legible(client, tmp_path, monkeypatch):
    test_client, _, empresa_id, cuenta_id = client
    _activar_modo_produccion(monkeypatch, tmp_path)
    _subir_pdf_de_ejemplo(test_client, empresa_id)

    respuesta = test_client.post(
        "/revisar/generar_sepa",
        data={"cuenta_id": str(cuenta_id), "sepa_incluir": ["1"], "sepa_liquido_1": ""},
    )

    assert respuesta.status_code == 400
    assert "importe" in respuesta.text.lower()


def test_generar_sepa_empleado_sin_iban_da_error_legible(client, tmp_path, monkeypatch):
    test_client, empleado_id, empresa_id, cuenta_id = client
    _activar_modo_produccion(monkeypatch, tmp_path)

    conn = main_module.get_connection()
    try:
        actualizar_iban_empleado(conn, empleado_id, None)
    finally:
        conn.close()

    _subir_pdf_de_ejemplo(test_client, empresa_id)

    respuesta = test_client.post(
        "/revisar/generar_sepa",
        data={"cuenta_id": str(cuenta_id), "sepa_incluir": ["1"], "sepa_liquido_1": "1.572,84"},
    )

    assert respuesta.status_code == 400
    assert "IBAN" in respuesta.text


def test_generar_sepa_rechaza_fila_sin_match_aunque_tenga_empleado_sugerido_con_iban(client, tmp_path, monkeypatch):
    """Regresión: emparejar_nomina() puede devolver metodo='sin_match' con un
    empleado_id relleno (el mejor candidato fuzzy, sugerido para revisión manual pero
    NO confirmado — ver app/matcher.py). Ese candidato nunca debe poder cobrar un SEPA
    solo porque tenga IBAN en su ficha; hace falta un match confirmado."""
    test_client, empleado_id, empresa_id, cuenta_id = client
    _activar_modo_produccion(monkeypatch, tmp_path)
    _subir_pdf_de_ejemplo(test_client, empresa_id)

    fila_original = main_module.estado_actual.filas[0]
    assert fila_original.metodo == "dni_exacto"
    assert fila_original.empleado_id == empleado_id  # tiene IBAN registrado, ver fixture `client`
    fila_sin_match = replace(fila_original, metodo="sin_match")
    main_module.estado_actual = replace(main_module.estado_actual, filas=[fila_sin_match])

    pagina_revision = test_client.get("/revisar")
    assert "sepa_liquido_1" not in pagina_revision.text  # la fila no debe ni aparecer en la tabla del SEPA

    respuesta = test_client.post(
        "/revisar/generar_sepa",
        data={"cuenta_id": str(cuenta_id), "sepa_incluir": ["1"], "sepa_liquido_1": "1.572,84"},
    )

    assert respuesta.status_code == 400
    assert "sin empleado emparejado" in respuesta.text
    ruta_salida = tmp_path / "salida" / NIF_MEDIFORM_PLUS / "2026-06" / "SEPA_2026-06.xml"
    assert not ruta_salida.exists()
