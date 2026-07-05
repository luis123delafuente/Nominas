import sqlite3

import pytest

from app.db import (
    actualizar_empleado,
    crear_empleado,
    crear_empresa,
    dar_baja_empleado,
    get_connection,
    init_db,
    listar_empleados,
    obtener_empleado,
    obtener_envio_previo,
    reactivar_empleado,
    registrar_envio,
)


@pytest.fixture
def conn():
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def empresa_id(conn):
    """Una empresa de ejemplo, para los tests de envios_log (que sí está ligado a empresa)."""
    cursor = conn.execute("INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Empresa Test", "X00000000"))
    conn.commit()
    return cursor.lastrowid


def test_crear_empresa(conn):
    empresa_id = crear_empresa(conn, "  NUESTRAFARMA PLUS SL  ", " b27523299 ")

    empresa = conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    assert empresa["nombre"] == "NUESTRAFARMA PLUS SL"
    assert empresa["nif"] == "B27523299"
    assert empresa["activa"] == 1


def test_crear_empresa_con_nif_duplicado_lanza_error_claro(conn):
    crear_empresa(conn, "Primera Empresa S.L.", "B88471149")

    with pytest.raises(sqlite3.IntegrityError):
        crear_empresa(conn, "Segunda Empresa S.L.", "B88471149")


def test_crear_empresa_con_nif_formato_invalido_lanza_error_claro(conn):
    with pytest.raises(ValueError):
        crear_empresa(conn, "Empresa Cualquiera", "NOESUNNIF")


def test_crear_y_obtener_empleado(conn):
    empleado_id = crear_empleado(conn, "Nicolas Alcalde Lasaosa", " 02349419s ", "nicolas@example.com", "2025-01-15")

    empleado = obtener_empleado(conn, empleado_id)
    assert empleado["nombre_completo"] == "Nicolas Alcalde Lasaosa"
    assert empleado["dni_nie"] == "02349419S"
    assert empleado["activo"] == 1
    assert empleado["fecha_baja"] is None


def test_dni_nie_duplicado_lanza_error_siempre(conn):
    # El DNI identifica a una persona física de forma única a nivel nacional:
    # dos empleados distintos con el mismo DNI nunca es válido, no hay "contexto de empresa".
    crear_empleado(conn, "Persona Uno", "12345678A", "uno@example.com", "2025-01-01")

    with pytest.raises(sqlite3.IntegrityError):
        crear_empleado(conn, "Persona Dos", "12345678A", "dos@example.com", "2025-02-01")


def test_listar_empleados_solo_activos(conn):
    activo_id = crear_empleado(conn, "Activo", "11111111A", "activo@example.com", "2025-01-01")
    baja_id = crear_empleado(conn, "De Baja", "22222222B", "baja@example.com", "2025-01-01")
    dar_baja_empleado(conn, baja_id, "2026-06-30")

    todos = listar_empleados(conn)
    activos = listar_empleados(conn, solo_activos=True)

    assert len(todos) == 2
    assert [e["id"] for e in activos] == [activo_id]


def test_dar_baja_no_borra_el_registro(conn):
    empleado_id = crear_empleado(conn, "Historico", "33333333C", "historico@example.com", "2025-01-01")
    dar_baja_empleado(conn, empleado_id, "2026-06-30")

    empleado = obtener_empleado(conn, empleado_id)
    assert empleado["activo"] == 0
    assert empleado["fecha_baja"] == "2026-06-30"


def test_reactivar_empleado_deshace_la_baja(conn):
    empleado_id = crear_empleado(conn, "Reactivado", "88889999H", "reactivado@example.com", "2025-01-01")
    dar_baja_empleado(conn, empleado_id, "2026-06-30")

    reactivar_empleado(conn, empleado_id)

    empleado = obtener_empleado(conn, empleado_id)
    assert empleado["activo"] == 1
    assert empleado["fecha_baja"] is None


def test_reactivar_empleado_no_crea_fila_nueva_ni_cambia_el_dni(conn):
    empleado_id = crear_empleado(conn, "Reactivado Dos", "77778889I", "reactivado2@example.com", "2025-01-01")
    dar_baja_empleado(conn, empleado_id, "2026-06-30")

    total_antes = len(listar_empleados(conn))
    reactivar_empleado(conn, empleado_id)
    total_despues = len(listar_empleados(conn))

    assert total_despues == total_antes  # ninguna fila nueva

    empleado = obtener_empleado(conn, empleado_id)
    assert empleado["id"] == empleado_id
    assert empleado["dni_nie"] == "77778889I"  # el DNI no cambia


def test_actualizar_empleado(conn):
    empleado_id = crear_empleado(conn, "Nombre Viejo", "44444444D", "viejo@example.com", "2025-01-01")

    actualizar_empleado(conn, empleado_id, email="nuevo@example.com")

    empleado = obtener_empleado(conn, empleado_id)
    assert empleado["email"] == "nuevo@example.com"
    assert empleado["nombre_completo"] == "Nombre Viejo"


def test_actualizar_empleado_rechaza_campos_no_permitidos(conn):
    empleado_id = crear_empleado(conn, "Nombre", "55555555E", "correo@example.com", "2025-01-01")

    with pytest.raises(ValueError):
        actualizar_empleado(conn, empleado_id, id=999)


def test_registrar_envio_en_modo_prueba_guarda_ambos_emails(conn, empresa_id):
    empleado_id = crear_empleado(conn, "Nombre", "66666666F", "empleado.real@example.com", "2025-01-01")

    envio_id = registrar_envio(
        conn,
        fecha_hora="2026-07-04T10:00:00",
        mes_nomina="2026-06",
        empleado_id=empleado_id,
        empresa_id=empresa_id,
        email_destino="pruebas@example.com",
        estado="enviado",
        email_produccion="empleado.real@example.com",
    )

    fila = conn.execute("SELECT * FROM envios_log WHERE id = ?", (envio_id,)).fetchone()
    assert fila["email_destino"] == "pruebas@example.com"
    assert fila["email_produccion"] == "empleado.real@example.com"
    assert fila["empresa_id"] == empresa_id


def test_registrar_envio_en_modo_produccion_no_necesita_email_produccion(conn, empresa_id):
    empleado_id = crear_empleado(conn, "Nombre", "77777777G", "empleado.real@example.com", "2025-01-01")

    envio_id = registrar_envio(
        conn,
        fecha_hora="2026-07-04T10:00:00",
        mes_nomina="2026-06",
        empleado_id=empleado_id,
        empresa_id=empresa_id,
        email_destino="empleado.real@example.com",
        estado="enviado",
    )

    fila = conn.execute("SELECT * FROM envios_log WHERE id = ?", (envio_id,)).fetchone()
    assert fila["email_destino"] == "empleado.real@example.com"
    assert fila["email_produccion"] is None


def test_obtener_envio_previo_no_mezcla_empresas_distintas(conn, empresa_id):
    # Caso real: la misma persona puede recibir nóminas de dos empresas del cliente el
    # mismo mes. Son envíos independientes — uno no debe marcar al otro como "ya enviado".
    otra_empresa_id = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", ("Otra Empresa S.L.", "Y11111111")
    ).lastrowid
    conn.commit()

    empleado_id = crear_empleado(conn, "Padre En Dos Empresas", "12345678A", "padre@example.com", "2025-01-01")

    registrar_envio(
        conn,
        fecha_hora="2026-07-01T10:00:00",
        mes_nomina="2026-06",
        empleado_id=empleado_id,
        empresa_id=empresa_id,
        email_destino="padre@example.com",
        estado="enviado",
    )

    previo_empresa_uno = obtener_envio_previo(conn, empleado_id, empresa_id, "2026-06")
    previo_otra_empresa = obtener_envio_previo(conn, empleado_id, otra_empresa_id, "2026-06")

    assert previo_empresa_uno is not None
    assert previo_otra_empresa is None  # el envío de la empresa 1 no "contamina" la empresa 2
