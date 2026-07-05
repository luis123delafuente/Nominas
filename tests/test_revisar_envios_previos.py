import os
import re

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import NIF_MEDIFORM_PLUS, NOMBRE_MEDIFORM_PLUS, crear_empleado, get_connection, init_db, registrar_envio

PDF_EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "entrada", "NOMINAS_062026.pdf")

pytestmark = pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO),
    reason="Requiere el PDF de ejemplo real en entrada/NOMINAS_062026.pdf (no versionado por ser dato sensible)",
)

# Del PDF de ejemplo: primera nómina, ALCALDE LASAOSA, NICOLAS, DNI 02349419S.
DNI_EMPLEADO = "02349419S"
NOMBRE_EMPLEADO = "Nicolás Alcalde Lasaosa"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """BD y carpeta de entrada temporales, para no tocar data/nominas.db ni entrada/ reales."""
    ruta_db = tmp_path / "test_nominas.db"
    monkeypatch.setattr(main_module, "get_connection", lambda db_path=ruta_db: get_connection(db_path))
    monkeypatch.setattr(main_module, "ENTRADA_DIR", tmp_path / "entrada")

    conn = get_connection(ruta_db)
    init_db(conn)
    # El NIF debe coincidir con el que trae de verdad el PDF de ejemplo (B82827635),
    # ya que ahora detectar_nominas() busca ese NIF concreto, no uno fijo.
    empresa_id = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", (NOMBRE_MEDIFORM_PLUS, NIF_MEDIFORM_PLUS)
    ).lastrowid
    conn.commit()
    empleado_id = crear_empleado(conn, NOMBRE_EMPLEADO, DNI_EMPLEADO, "nicolas@example.com", "2025-01-01")
    conn.close()

    with TestClient(main_module.app) as test_client:
        yield test_client, empleado_id, empresa_id


def _subir_pdf_de_ejemplo(test_client, empresa_id):
    # El mes ya no se envía en el formulario: se extrae del contenido del PDF
    # (campo PERIODO de la primera nómina). El PDF de ejemplo es de "2026-06".
    with open(PDF_EJEMPLO, "rb") as f:
        return test_client.post(
            "/subir",
            files={"pdf": ("NOMINAS_062026.pdf", f, "application/pdf")},
            data={"empresa_id": empresa_id},
            follow_redirects=True,
        )


def _checkbox_de_la_fila(html: str, numero: int) -> str:
    coincidencia = re.search(rf'<input type="checkbox" name="incluir" value="{numero}"[^>]*>', html)
    assert coincidencia is not None, f"No se encontró el checkbox de la fila {numero}"
    return coincidencia.group(0)


def test_sin_envios_previos_no_muestra_aviso(client):
    test_client, _, empresa_id = client

    respuesta = _subir_pdf_de_ejemplo(test_client, empresa_id)

    assert respuesta.status_code == 200
    assert "Ya se envió" not in respuesta.text

    # Empleado emparejado por DNI exacto y sin envío previo: sigue autoconfirmado, como hasta ahora.
    checkbox = _checkbox_de_la_fila(respuesta.text, 1)
    assert "checked" in checkbox


def test_con_envio_previo_muestra_aviso_y_desmarca_el_checkbox(client):
    test_client, empleado_id, empresa_id = client

    conn = main_module.get_connection()
    try:
        registrar_envio(
            conn,
            fecha_hora="2026-07-01T10:00:00",
            mes_nomina="2026-06",
            empleado_id=empleado_id,
            empresa_id=empresa_id,
            email_destino="nicolas@example.com",
            estado="enviado",
        )
    finally:
        conn.close()

    respuesta = _subir_pdf_de_ejemplo(test_client, empresa_id)

    assert respuesta.status_code == 200
    assert "Ya se envió el 2026-07-01T10:00:00" in respuesta.text
    assert "revisa antes de reenviar" in respuesta.text

    # La fila de este empleado (nómina número 1 en el PDF de ejemplo) sale SIN marcar por defecto...
    checkbox = _checkbox_de_la_fila(respuesta.text, 1)
    assert "checked" not in checkbox

    # ...pero sigue disponible para marcarla y reenviar a propósito (no está deshabilitada).
    assert "disabled" not in checkbox


def test_corregir_mes_en_revisar_recalcula_aviso_ya_enviado(client):
    test_client, empleado_id, empresa_id = client

    # Envío previo registrado en "2026-05" (mes distinto al detectado del PDF, "2026-06").
    conn = main_module.get_connection()
    try:
        registrar_envio(
            conn,
            fecha_hora="2026-06-01T10:00:00",
            mes_nomina="2026-05",
            empleado_id=empleado_id,
            empresa_id=empresa_id,
            email_destino="nicolas@example.com",
            estado="enviado",
        )
    finally:
        conn.close()

    respuesta = _subir_pdf_de_ejemplo(test_client, empresa_id)
    assert respuesta.status_code == 200
    # El mes detectado (2026-06) no coincide con el del envío previo (2026-05): sin aviso.
    assert "Ya se envió" not in respuesta.text

    # Al corregir el mes a "2026-05" en la pantalla de revisión, debe recalcularse el aviso.
    respuesta_corregida = test_client.post(
        "/revisar/mes_nomina", data={"mes_nomina": "2026-05"}, follow_redirects=True
    )
    assert respuesta_corregida.status_code == 200
    assert "Ya se envió el 2026-06-01T10:00:00" in respuesta_corregida.text
    checkbox = _checkbox_de_la_fila(respuesta_corregida.text, 1)
    assert "checked" not in checkbox
