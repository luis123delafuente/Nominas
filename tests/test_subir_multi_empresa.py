import os

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
    conn.close()

    with TestClient(main_module.app) as test_client:
        yield test_client


def _subir_pdf_de_ejemplo(test_client, empresa_id, mes_nomina="2026-06"):
    with open(PDF_EJEMPLO, "rb") as f:
        return test_client.post(
            "/subir",
            files={"pdf": ("NOMINAS_062026.pdf", f, "application/pdf")},
            data={"mes_nomina": mes_nomina, "empresa_id": empresa_id},
            follow_redirects=True,
        )


def test_subir_seleccionando_la_empresa_correcta_funciona_como_siempre(client):
    conn = main_module.get_connection()
    try:
        empresa_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", (NOMBRE_MEDIFORM_PLUS, NIF_MEDIFORM_PLUS)
        ).lastrowid
        conn.commit()
        crear_empleado(conn, NOMBRE_EMPLEADO, DNI_EMPLEADO, "nicolas@example.com", "2025-01-01")
    finally:
        conn.close()

    respuesta = _subir_pdf_de_ejemplo(client, empresa_id)

    assert respuesta.status_code == 200
    assert "Revisión de nóminas detectadas" in respuesta.text
    assert "ALCALDE LASAOSA, NICOLAS" in respuesta.text
    assert "DNI exacto" in respuesta.text


def test_subir_con_empresa_equivocada_falla_y_menciona_el_nif_real(client):
    conn = main_module.get_connection()
    try:
        empresa_incorrecta_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Otra Empresa Del Cliente S.L.", "Z11111116")
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    respuesta = _subir_pdf_de_ejemplo(client, empresa_incorrecta_id)

    assert respuesta.status_code == 400
    assert "No se ha detectado ninguna nómina de Otra Empresa Del Cliente S.L." in respuesta.text
    assert f"Se ha detectado un NIF distinto: {NIF_MEDIFORM_PLUS}" in respuesta.text
    assert "¿has seleccionado la empresa correcta?" in respuesta.text


def test_aviso_de_ya_enviado_no_se_mezcla_entre_empresas_distintas(client):
    # Caso real: la misma persona puede recibir nóminas de dos empresas del cliente el
    # mismo mes. Que ya se le enviara la nómina de una empresa no debe marcar como
    # "ya enviado" la nómina de la otra empresa para esa misma persona y mes.
    conn = main_module.get_connection()
    try:
        empresa_a_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", (NOMBRE_MEDIFORM_PLUS, NIF_MEDIFORM_PLUS)
        ).lastrowid
        empresa_b_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Otra Empresa Del Cliente S.L.", "Y22222229")
        ).lastrowid
        conn.commit()

        empleado_id = crear_empleado(conn, NOMBRE_EMPLEADO, DNI_EMPLEADO, "nicolas@example.com", "2025-01-01")

        # Ya se le envió la nómina de la empresa B este mes...
        registrar_envio(
            conn,
            fecha_hora="2026-07-01T10:00:00",
            mes_nomina="2026-06",
            empleado_id=empleado_id,
            empresa_id=empresa_b_id,
            email_destino="nicolas@example.com",
            estado="enviado",
        )
    finally:
        conn.close()

    # ...pero subir el PDF de la empresa A (el mismo mes) no debe mostrar el aviso de "ya enviado".
    respuesta_empresa_a = _subir_pdf_de_ejemplo(client, empresa_a_id)
    assert respuesta_empresa_a.status_code == 200
    assert "Ya se envió" not in respuesta_empresa_a.text

    # Si ahora también se envía (de verdad) la de la empresa A, y se vuelve a subir, sí debe avisar.
    conn = main_module.get_connection()
    try:
        registrar_envio(
            conn,
            fecha_hora="2026-07-02T10:00:00",
            mes_nomina="2026-06",
            empleado_id=empleado_id,
            empresa_id=empresa_a_id,
            email_destino="nicolas@example.com",
            estado="enviado",
        )
    finally:
        conn.close()

    respuesta_empresa_a_otra_vez = _subir_pdf_de_ejemplo(client, empresa_a_id)
    assert "Ya se envió el 2026-07-02T10:00:00" in respuesta_empresa_a_otra_vez.text
