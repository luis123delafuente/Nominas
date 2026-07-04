import sqlite3

import pytest

from app.db import (
    actualizar_empleado,
    crear_empleado,
    dar_baja_empleado,
    get_connection,
    init_db,
    listar_empleados,
    obtener_empleado,
    reactivar_empleado,
    registrar_envio,
)


@pytest.fixture
def conn():
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


def test_crear_y_obtener_empleado(conn):
    empleado_id = crear_empleado(conn, "Nicolas Alcalde Lasaosa", " 02349419s ", "nicolas@example.com", "2025-01-15")

    empleado = obtener_empleado(conn, empleado_id)
    assert empleado["nombre_completo"] == "Nicolas Alcalde Lasaosa"
    assert empleado["dni_nie"] == "02349419S"
    assert empleado["activo"] == 1
    assert empleado["fecha_baja"] is None


def test_dni_nie_duplicado_lanza_error(conn):
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


def test_registrar_envio_en_modo_prueba_guarda_ambos_emails(conn):
    empleado_id = crear_empleado(conn, "Nombre", "66666666F", "empleado.real@example.com", "2025-01-01")

    envio_id = registrar_envio(
        conn,
        fecha_hora="2026-07-04T10:00:00",
        mes_nomina="2026-06",
        empleado_id=empleado_id,
        email_destino="pruebas@example.com",
        estado="enviado",
        email_produccion="empleado.real@example.com",
    )

    fila = conn.execute("SELECT * FROM envios_log WHERE id = ?", (envio_id,)).fetchone()
    assert fila["email_destino"] == "pruebas@example.com"
    assert fila["email_produccion"] == "empleado.real@example.com"


def test_registrar_envio_en_modo_produccion_no_necesita_email_produccion(conn):
    empleado_id = crear_empleado(conn, "Nombre", "77777777G", "empleado.real@example.com", "2025-01-01")

    envio_id = registrar_envio(
        conn,
        fecha_hora="2026-07-04T10:00:00",
        mes_nomina="2026-06",
        empleado_id=empleado_id,
        email_destino="empleado.real@example.com",
        estado="enviado",
    )

    fila = conn.execute("SELECT * FROM envios_log WHERE id = ?", (envio_id,)).fetchone()
    assert fila["email_destino"] == "empleado.real@example.com"
    assert fila["email_produccion"] is None
