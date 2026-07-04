from unittest.mock import Mock

import pytest

from app.config import Configuracion
from app.db import crear_empleado, get_connection, init_db
from app.mailer_macos import (
    ConfiguracionInvalida,
    NominaParaEnviar,
    _construir_script_envio,
    enviar_lote,
    enviar_nomina,
    nota_modo_prueba,
    resolver_destinatario,
)


def test_modo_prueba_redirige_siempre_al_email_de_prueba():
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")

    destinatario = resolver_destinatario("empleado.real@example.com", config)

    assert destinatario.email_envio == "pruebas@example.com"
    assert destinatario.email_produccion == "empleado.real@example.com"
    assert destinatario.es_modo_prueba is True


def test_modo_produccion_usa_el_email_real_del_empleado():
    config = Configuracion(modo_envio="produccion", email_prueba="pruebas@example.com")

    destinatario = resolver_destinatario("empleado.real@example.com", config)

    assert destinatario.email_envio == "empleado.real@example.com"
    assert destinatario.email_produccion is None
    assert destinatario.es_modo_prueba is False


def test_modo_prueba_sin_email_de_prueba_configurado_lanza_error_claro():
    config = Configuracion(modo_envio="prueba", email_prueba=None)

    with pytest.raises(ConfiguracionInvalida):
        resolver_destinatario("empleado.real@example.com", config)


def test_modo_prueba_ignora_por_completo_el_email_del_empleado():
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")

    for email_empleado in ["a@x.com", "otro@y.com", "cualquiera@z.com"]:
        destinatario = resolver_destinatario(email_empleado, config)
        assert destinatario.email_envio == "pruebas@example.com"


def test_nota_modo_prueba_visible_con_el_email_real():
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")
    destinatario = resolver_destinatario("empleado.real@example.com", config)

    nota = nota_modo_prueba(destinatario)

    assert nota is not None
    assert "empleado.real@example.com" in nota


def test_nota_modo_prueba_es_none_en_produccion():
    config = Configuracion(modo_envio="produccion", email_prueba="pruebas@example.com")
    destinatario = resolver_destinatario("empleado.real@example.com", config)

    assert nota_modo_prueba(destinatario) is None


# --- Construcción del AppleScript ---


def test_construir_script_envio_incluye_destinatario_asunto_cuerpo_y_adjunto():
    script = _construir_script_envio(
        email_destino="destino@example.com",
        asunto="Nómina 2026-06",
        cuerpo="Hola Nicolás,\n\nAdjuntamos tu nómina.",
        ruta_adjunto="/tmp/01_nicolas.pdf",
    )

    assert 'address:"destino@example.com"' in script
    assert 'subject:"Nómina 2026-06"' in script
    assert "Adjuntamos tu nómina" in script
    assert 'POSIX file "/tmp/01_nicolas.pdf" as alias' in script
    assert 'tell application "Mail"' in script
    assert "send nuevoMensaje" in script


def test_construir_script_envio_escapa_comillas_para_no_romper_el_applescript():
    script = _construir_script_envio(
        email_destino="destino@example.com",
        asunto='Nómina con "comillas"',
        cuerpo="cuerpo normal",
        ruta_adjunto="/tmp/archivo.pdf",
    )

    assert 'Nómina con \\"comillas\\"' in script


# --- enviar_nomina / enviar_lote (sin llamar a Mail.app real) ---


@pytest.fixture
def conn():
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


def _fake_run_ok(*args, **kwargs):
    return Mock(returncode=0, stderr="")


def _fake_run_error(*args, **kwargs):
    return Mock(returncode=1, stderr="Mail.app no respondió")


def test_enviar_nomina_exitoso_registra_estado_enviado(conn, tmp_path, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")

    monkeypatch.setattr("app.mailer_macos.subprocess.run", _fake_run_ok)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf), config
    )

    assert resultado.estado == "enviado"
    assert resultado.email_destino == "nicolas@example.com"

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["estado"] == "enviado"
    assert fila["email_destino"] == "nicolas@example.com"
    assert fila["email_produccion"] is None


def test_enviar_nomina_en_modo_prueba_registra_email_produccion(conn, tmp_path, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")

    monkeypatch.setattr("app.mailer_macos.subprocess.run", _fake_run_ok)
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")

    resultado = enviar_nomina(
        conn, empleado_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf), config
    )

    assert resultado.estado == "enviado"
    assert resultado.email_destino == "pruebas@example.com"

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["email_destino"] == "pruebas@example.com"
    assert fila["email_produccion"] == "nicolas@example.com"


def test_enviar_nomina_falla_si_falta_el_adjunto_y_no_llama_a_osascript(conn, tmp_path, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf_inexistente = tmp_path / "no_existe.pdf"

    llamadas = []
    monkeypatch.setattr("app.mailer_macos.subprocess.run", lambda *a, **k: llamadas.append(1))
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn,
        empleado_id,
        "Nicolás Alcalde Lasaosa",
        "nicolas@example.com",
        "2026-06",
        str(ruta_pdf_inexistente),
        config,
    )

    assert resultado.estado == "error"
    assert "no existe" in resultado.detalle
    assert llamadas == []  # nunca se llegó a invocar osascript

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["estado"] == "error"


def test_enviar_nomina_falla_si_osascript_devuelve_error(conn, tmp_path, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")

    monkeypatch.setattr("app.mailer_macos.subprocess.run", _fake_run_error)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf), config
    )

    assert resultado.estado == "error"
    assert "Mail.app no respondió" in resultado.detalle

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["estado"] == "error"
    assert "Mail.app no respondió" in fila["detalle"]


def test_enviar_lote_continua_tras_un_fallo_individual(conn, tmp_path, monkeypatch):
    empleado_ok_id = crear_empleado(conn, "Empleado Ok", "11111111A", "ok@example.com", "2025-01-01")
    empleado_falla_id = crear_empleado(conn, "Empleado Falla", "22222222B", "falla@example.com", "2025-01-01")

    ruta_pdf_ok = tmp_path / "ok.pdf"
    ruta_pdf_ok.write_bytes(b"%PDF-1.7 contenido")
    ruta_pdf_inexistente = tmp_path / "no_existe.pdf"

    monkeypatch.setattr("app.mailer_macos.subprocess.run", _fake_run_ok)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    nominas = [
        NominaParaEnviar(empleado_falla_id, "Empleado Falla", "falla@example.com", "2026-06", str(ruta_pdf_inexistente)),
        NominaParaEnviar(empleado_ok_id, "Empleado Ok", "ok@example.com", "2026-06", str(ruta_pdf_ok)),
    ]

    resumen = enviar_lote(conn, nominas, config)

    assert resumen.enviados == 1
    assert resumen.errores == 1
    assert len(resumen.resultados) == 2

    filas = conn.execute("SELECT * FROM envios_log ORDER BY empleado_id").fetchall()
    assert len(filas) == 2
