import smtplib

import pytest

from app.config import Configuracion
from app.db import crear_empleado, get_connection, guardar_credenciales_smtp, init_db
from app.mailer_smtp import (
    ConfiguracionInvalida,
    NominaParaEnviar,
    enviar_lote,
    enviar_nomina,
    nota_modo_prueba,
    resolver_destinatario,
)

# --- resolver_destinatario / nota_modo_prueba: mismo comportamiento que en Mail.app ---


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


# --- enviar_nomina / enviar_lote, con un servidor SMTP simulado (sin red real) ---


@pytest.fixture
def conn():
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def ruta_clave(tmp_path):
    return tmp_path / "clave_cifrado.key"


@pytest.fixture
def empresa_id(conn):
    cursor = conn.execute("INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Empresa Test", "X00000000"))
    conn.commit()
    return cursor.lastrowid


class _ServidorSMTPFalso:
    """Sustituye a smtplib.SMTP/SMTP_SSL. Cada instancia se registra en `instancias`
    (de clase) para poder inspeccionar, en el test, qué se intentó enviar."""

    instancias: list = []

    def __init__(self, host, puerto, timeout=None):
        self.host = host
        self.puerto = puerto
        self.starttls_llamado = False
        self.login_args = None
        self.mensaje_enviado = None
        type(self).instancias.append(self)

    def starttls(self):
        self.starttls_llamado = True

    def login(self, usuario, password):
        self.login_args = (usuario, password)

    def send_message(self, mensaje):
        self.mensaje_enviado = mensaje

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _ServidorSMTPFallaLogin(_ServidorSMTPFalso):
    def login(self, usuario, password):
        raise smtplib.SMTPAuthenticationError(535, b"Credenciales invalidas")


@pytest.fixture(autouse=True)
def _limpiar_instancias_smtp_falsas():
    _ServidorSMTPFalso.instancias = []
    yield
    _ServidorSMTPFalso.instancias = []


def _configurar_smtp_falso(monkeypatch, clase=_ServidorSMTPFalso):
    monkeypatch.setattr("app.mailer_smtp.smtplib.SMTP", clase)
    monkeypatch.setattr("app.mailer_smtp.smtplib.SMTP_SSL", clase)


def test_enviar_nomina_exitoso_registra_estado_enviado(conn, empresa_id, tmp_path, ruta_clave, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")
    guardar_credenciales_smtp(
        conn, empresa_id, "smtp.gmail.com", 587, "empresa@gmail.com", "contraseña-app", ruta_clave=ruta_clave
    )

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn,
        empleado_id,
        empresa_id,
        "Nicolás Alcalde Lasaosa",
        "nicolas@example.com",
        "2026-06",
        str(ruta_pdf),
        config,
        ruta_clave=ruta_clave,
    )

    assert resultado.estado == "enviado"
    assert resultado.email_destino == "nicolas@example.com"

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["estado"] == "enviado"
    assert fila["email_destino"] == "nicolas@example.com"
    assert fila["email_produccion"] is None
    assert fila["empresa_id"] == empresa_id

    servidor = _ServidorSMTPFalso.instancias[0]
    assert servidor.host == "smtp.gmail.com"
    assert servidor.puerto == 587
    assert servidor.starttls_llamado is True  # 587 -> STARTTLS, no TLS implícito
    assert servidor.login_args == ("empresa@gmail.com", "contraseña-app")
    assert servidor.mensaje_enviado["To"] == "nicolas@example.com"
    assert servidor.mensaje_enviado["From"] == "empresa@gmail.com"
    assert servidor.mensaje_enviado.get_content_disposition() is None  # multipart: el texto va en el primer bloque
    adjuntos = list(servidor.mensaje_enviado.iter_attachments())
    assert len(adjuntos) == 1
    assert adjuntos[0].get_filename() == "01_nicolas.pdf"


def test_enviar_nomina_puerto_465_usa_tls_implicito_sin_starttls(conn, empresa_id, tmp_path, ruta_clave, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")
    guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 465, "empresa@gmail.com", "clave", ruta_clave=ruta_clave)

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, empresa_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf),
        config, ruta_clave=ruta_clave,
    )

    assert resultado.estado == "enviado"
    servidor = _ServidorSMTPFalso.instancias[0]
    assert servidor.puerto == 465
    assert servidor.starttls_llamado is False  # TLS ya implícito, no hace falta


def test_enviar_nomina_en_modo_prueba_registra_email_produccion(conn, empresa_id, tmp_path, ruta_clave, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")
    guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "empresa@gmail.com", "clave", ruta_clave=ruta_clave)

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")

    resultado = enviar_nomina(
        conn, empleado_id, empresa_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf),
        config, ruta_clave=ruta_clave,
    )

    assert resultado.estado == "enviado"
    assert resultado.email_destino == "pruebas@example.com"

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["email_destino"] == "pruebas@example.com"
    assert fila["email_produccion"] == "nicolas@example.com"

    servidor = _ServidorSMTPFalso.instancias[0]
    assert servidor.mensaje_enviado["To"] == "pruebas@example.com"  # el envío real también se redirige, no solo el log


def test_enviar_nomina_falla_si_falta_el_adjunto_y_no_llega_a_conectar(conn, empresa_id, tmp_path, ruta_clave, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf_inexistente = tmp_path / "no_existe.pdf"
    guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "empresa@gmail.com", "clave", ruta_clave=ruta_clave)

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, empresa_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06",
        str(ruta_pdf_inexistente), config, ruta_clave=ruta_clave,
    )

    assert resultado.estado == "error"
    assert "no existe" in resultado.detalle
    assert _ServidorSMTPFalso.instancias == []  # nunca se llegó a conectar


def test_enviar_nomina_sin_credenciales_smtp_configuradas_falla_de_forma_clara(conn, empresa_id, tmp_path, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")
    # A propósito: no se llama a guardar_credenciales_smtp().

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, empresa_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf), config
    )

    assert resultado.estado == "error"
    assert "credenciales SMTP" in resultado.detalle
    assert _ServidorSMTPFalso.instancias == []


def test_enviar_nomina_falla_si_el_servidor_rechaza_el_login(conn, empresa_id, tmp_path, ruta_clave, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")
    guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "empresa@gmail.com", "clave-mala", ruta_clave=ruta_clave)

    _configurar_smtp_falso(monkeypatch, clase=_ServidorSMTPFallaLogin)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, empresa_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf),
        config, ruta_clave=ruta_clave,
    )

    assert resultado.estado == "error"
    assert "Credenciales invalidas" in resultado.detalle or "535" in resultado.detalle

    fila = conn.execute("SELECT * FROM envios_log WHERE empleado_id = ?", (empleado_id,)).fetchone()
    assert fila["estado"] == "error"


def test_enviar_nomina_falla_si_la_empresa_no_existe(conn, tmp_path, monkeypatch):
    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    ruta_pdf = tmp_path / "01_nicolas.pdf"
    ruta_pdf.write_bytes(b"%PDF-1.7 contenido de prueba")

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado = enviar_nomina(
        conn, empleado_id, 99999, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf), config
    )

    assert resultado.estado == "error"
    assert "99999" in resultado.detalle
    assert _ServidorSMTPFalso.instancias == []


def test_asunto_y_cuerpo_mencionan_la_empresa_y_distinguen_entre_empresas_distintas(conn, tmp_path, ruta_clave, monkeypatch):
    empresa_a_id = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("MEDIFORM PLUS S.L.", "B82827635")
    ).lastrowid
    empresa_b_id = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("NUESTRAFARMA PLUS SL", "B27523299")
    ).lastrowid
    conn.commit()
    guardar_credenciales_smtp(conn, empresa_a_id, "smtp.gmail.com", 587, "a@gmail.com", "clave-a", ruta_clave=ruta_clave)
    guardar_credenciales_smtp(
        conn, empresa_b_id, "smtp.office365.com", 587, "b@nuestrafarma.com", "clave-b", ruta_clave=ruta_clave
    )

    empleado_id = crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")

    ruta_pdf_a = tmp_path / "a.pdf"
    ruta_pdf_b = tmp_path / "b.pdf"
    ruta_pdf_a.write_bytes(b"%PDF-1.7 contenido")
    ruta_pdf_b.write_bytes(b"%PDF-1.7 contenido")

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    resultado_a = enviar_nomina(
        conn, empleado_id, empresa_a_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf_a),
        config, ruta_clave=ruta_clave,
    )
    resultado_b = enviar_nomina(
        conn, empleado_id, empresa_b_id, "Nicolás Alcalde Lasaosa", "nicolas@example.com", "2026-06", str(ruta_pdf_b),
        config, ruta_clave=ruta_clave,
    )

    assert resultado_a.estado == "enviado"
    assert resultado_b.estado == "enviado"
    assert len(_ServidorSMTPFalso.instancias) == 2
    servidor_a, servidor_b = _ServidorSMTPFalso.instancias

    assert servidor_a.host == "smtp.gmail.com"
    assert servidor_a.login_args == ("a@gmail.com", "clave-a")
    assert "MEDIFORM PLUS S.L." in servidor_a.mensaje_enviado["Subject"]
    assert "NUESTRAFARMA PLUS SL" not in servidor_a.mensaje_enviado["Subject"]

    assert servidor_b.host == "smtp.office365.com"
    assert servidor_b.login_args == ("b@nuestrafarma.com", "clave-b")
    assert "NUESTRAFARMA PLUS SL" in servidor_b.mensaje_enviado["Subject"]
    assert "MEDIFORM PLUS S.L." not in servidor_b.mensaje_enviado["Subject"]


def test_enviar_lote_continua_tras_un_fallo_individual(conn, empresa_id, tmp_path, ruta_clave, monkeypatch):
    empleado_ok_id = crear_empleado(conn, "Empleado Ok", "11111111A", "ok@example.com", "2025-01-01")
    empleado_falla_id = crear_empleado(conn, "Empleado Falla", "22222222B", "falla@example.com", "2025-01-01")
    guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "empresa@gmail.com", "clave", ruta_clave=ruta_clave)

    ruta_pdf_ok = tmp_path / "ok.pdf"
    ruta_pdf_ok.write_bytes(b"%PDF-1.7 contenido")
    ruta_pdf_inexistente = tmp_path / "no_existe.pdf"

    _configurar_smtp_falso(monkeypatch)
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    nominas = [
        NominaParaEnviar(
            empleado_falla_id, empresa_id, "Empleado Falla", "falla@example.com", "2026-06", str(ruta_pdf_inexistente)
        ),
        NominaParaEnviar(empleado_ok_id, empresa_id, "Empleado Ok", "ok@example.com", "2026-06", str(ruta_pdf_ok)),
    ]

    resumen = enviar_lote(conn, nominas, config, ruta_clave=ruta_clave)

    assert resumen.enviados == 1
    assert resumen.errores == 1
    assert len(resumen.resultados) == 2

    filas = conn.execute("SELECT * FROM envios_log ORDER BY empleado_id").fetchall()
    assert len(filas) == 2
