import fitz
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

import app.main as main_module
from app.db import crear_empleado, get_connection, init_db
from app.main import FilaRevision, LoteRevision


def _crear_pdf_dummy(ruta, texto: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), texto)
    doc.save(str(ruta))
    doc.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """BD y carpeta de salida temporales, para no tocar data/nominas.db ni salida/ reales."""
    ruta_db = tmp_path / "test_nominas.db"
    salida_dir = tmp_path / "salida"
    monkeypatch.setattr(main_module, "get_connection", lambda db_path=ruta_db: get_connection(db_path))
    monkeypatch.setattr(main_module, "SALIDA_DIR", salida_dir)
    # No se configuran credenciales_smtp para estas empresas de prueba: enviar_nomina()
    # fallará de forma controlada (ConfiguracionInvalida, capturada internamente) sin
    # llegar a intentar una conexión SMTP real. Esta prueba solo verifica el cifrado y
    # la separación por carpetas, que ocurren antes de intentar el envío.

    conn = get_connection(ruta_db)
    init_db(conn)
    conn.close()

    with TestClient(main_module.app) as test_client:
        yield test_client, salida_dir


def _confirmar_una_nomina(test_client, ruta_pdf_maestro, empresa_id, mes_nomina, empleado_id):
    fila = FilaRevision(
        numero=1,
        nombre_pdf="APELLIDO, NOMBRE",
        dni_pdf="12345678A",
        pagina_inicio=0,
        pagina_fin=0,
        metodo="dni_exacto",
        score_nombre=100.0,
        empleado_id=empleado_id,
        empleado_nombre="Nombre Empleado",
        empleado_email="empleado@example.com",
        empleado_dni="12345678A",
        envio_previo_fecha=None,
        incluir_por_defecto=True,
        liquido_a_percibir=None,
        liquido_metodo="manual",
    )
    main_module.estado_actual = LoteRevision(
        ruta_pdf_maestro=str(ruta_pdf_maestro), mes_nomina=mes_nomina, empresa_id=empresa_id, filas=[fila]
    )
    return test_client.post("/revisar/confirmar", data={"incluir": "1"})


def test_cifrar_dos_empresas_mismo_mes_genera_carpetas_separadas_sin_colision(client, tmp_path):
    test_client, salida_dir = client

    conn = main_module.get_connection()
    try:
        empresa_a_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Empresa A S.L.", "B11111114")
        ).lastrowid
        empresa_b_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Empresa B S.L.", "B22222223")
        ).lastrowid
        conn.commit()
        empleado_id = crear_empleado(conn, "Nombre Empleado", "12345678A", "empleado@example.com", "2025-01-01")
    finally:
        conn.close()

    pdf_a = tmp_path / "maestro_a.pdf"
    pdf_b = tmp_path / "maestro_b.pdf"
    _crear_pdf_dummy(pdf_a, "Nomina de la empresa A")
    _crear_pdf_dummy(pdf_b, "Nomina de la empresa B")

    respuesta_a = _confirmar_una_nomina(test_client, pdf_a, empresa_a_id, "2026-06", empleado_id)
    respuesta_b = _confirmar_una_nomina(test_client, pdf_b, empresa_b_id, "2026-06", empleado_id)

    assert respuesta_a.status_code == 200
    assert respuesta_b.status_code == 200

    ruta_esperada_a = salida_dir / "B11111114" / "2026-06" / "01_Nombre_Empleado.pdf"
    ruta_esperada_b = salida_dir / "B22222223" / "2026-06" / "01_Nombre_Empleado.pdf"

    assert ruta_esperada_a.exists()
    assert ruta_esperada_b.exists()
    assert ruta_esperada_a != ruta_esperada_b  # carpetas distintas: mismo nombre de archivo, sin colisión

    # Contenido distinto: cada uno cifrado a partir de las páginas de su propio PDF maestro.
    reader_a = PdfReader(str(ruta_esperada_a))
    reader_a.decrypt("12345678A")
    texto_a = reader_a.pages[0].extract_text()

    reader_b = PdfReader(str(ruta_esperada_b))
    reader_b.decrypt("12345678A")
    texto_b = reader_b.pages[0].extract_text()

    assert "empresa A" in texto_a
    assert "empresa B" in texto_b
    assert texto_a != texto_b
