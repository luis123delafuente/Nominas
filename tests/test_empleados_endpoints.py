import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import get_connection, init_db, listar_empleados, obtener_empleado


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Cada test corre contra una BD SQLite temporal, para no tocar data/nominas.db."""
    ruta_db = tmp_path / "test_nominas.db"
    monkeypatch.setattr(main_module, "get_connection", lambda db_path=ruta_db: get_connection(db_path))

    conn = get_connection(ruta_db)
    init_db(conn)
    conn.close()

    with TestClient(main_module.app) as test_client:
        yield test_client


def _buscar_empleado_por_dni(dni_nie: str):
    conn = main_module.get_connection()
    try:
        return next(e for e in listar_empleados(conn) if e["dni_nie"] == dni_nie)
    finally:
        conn.close()


def test_alta_de_empleado_correcta(client):
    respuesta = client.post(
        "/empleados/guardar",
        data={"empleado_id": "", "nombre_completo": "Persona Nueva", "dni_nie": "12345678A", "email": "nueva@example.com"},
        follow_redirects=True,
    )

    assert respuesta.status_code == 200
    assert "Persona Nueva" in respuesta.text
    assert "dado de alta" in respuesta.text


def test_alta_con_dni_duplicado_da_error_legible_no_500(client):
    datos = {"empleado_id": "", "nombre_completo": "Primero", "dni_nie": "87654321B", "email": "primero@example.com"}
    client.post("/empleados/guardar", data=datos)

    respuesta = client.post(
        "/empleados/guardar",
        data={"empleado_id": "", "nombre_completo": "Segundo", "dni_nie": "87654321B", "email": "segundo@example.com"},
    )

    assert respuesta.status_code == 400
    assert "Ya existe" in respuesta.text
    assert "87654321B" in respuesta.text


def test_alta_con_dni_formato_invalido_da_error_legible(client):
    respuesta = client.post(
        "/empleados/guardar",
        data={"empleado_id": "", "nombre_completo": "Alguien", "dni_nie": "NOESUNDNI", "email": "alguien@example.com"},
    )

    assert respuesta.status_code == 400
    assert "formato inválido" in respuesta.text


def test_edicion_de_un_campo(client):
    client.post(
        "/empleados/guardar",
        data={
            "empleado_id": "",
            "nombre_completo": "Nombre Original",
            "dni_nie": "11112222C",
            "email": "original@example.com",
        },
    )
    empleado_id = _buscar_empleado_por_dni("11112222C")["id"]

    respuesta = client.post(
        "/empleados/guardar",
        data={
            "empleado_id": str(empleado_id),
            "nombre_completo": "Nombre Original",
            "dni_nie": "11112222C",
            "email": "actualizado@example.com",
        },
        follow_redirects=True,
    )

    assert respuesta.status_code == 200
    assert "actualizado" in respuesta.text.lower()

    conn = main_module.get_connection()
    try:
        empleado = obtener_empleado(conn, empleado_id)
    finally:
        conn.close()
    assert empleado["email"] == "actualizado@example.com"
    assert empleado["nombre_completo"] == "Nombre Original"  # el resto de campos no cambia


def test_dar_de_baja_no_borra_el_registro(client):
    client.post(
        "/empleados/guardar",
        data={
            "empleado_id": "",
            "nombre_completo": "Persona A Dar De Baja",
            "dni_nie": "99998888D",
            "email": "baja@example.com",
        },
    )
    empleado_id = _buscar_empleado_por_dni("99998888D")["id"]

    respuesta = client.post(f"/empleados/{empleado_id}/baja", follow_redirects=True)

    assert respuesta.status_code == 200
    assert "dado de baja" in respuesta.text

    conn = main_module.get_connection()
    try:
        empleado = obtener_empleado(conn, empleado_id)
    finally:
        conn.close()

    assert empleado is not None  # sigue existiendo el registro
    assert empleado["activo"] == 0
    assert empleado["fecha_baja"] is not None


def test_reactivar_empleado_vuelve_a_mostrarlo_como_activo_por_defecto(client):
    client.post(
        "/empleados/guardar",
        data={
            "empleado_id": "",
            "nombre_completo": "Persona A Reactivar",
            "dni_nie": "44445555J",
            "email": "reactivar@example.com",
        },
    )
    empleado_id = _buscar_empleado_por_dni("44445555J")["id"]
    client.post(f"/empleados/{empleado_id}/baja")

    respuesta = client.post(f"/empleados/{empleado_id}/reactivar", follow_redirects=True)

    assert respuesta.status_code == 200
    assert "reactivado" in respuesta.text.lower()

    conn = main_module.get_connection()
    try:
        empleado = obtener_empleado(conn, empleado_id)
    finally:
        conn.close()
    assert empleado["activo"] == 1
    assert empleado["fecha_baja"] is None

    respuesta_listado_activos = client.get("/empleados")
    assert "Persona A Reactivar" in respuesta_listado_activos.text


def test_listado_por_defecto_solo_muestra_activos(client):
    client.post(
        "/empleados/guardar",
        data={
            "empleado_id": "",
            "nombre_completo": "Activo Visible",
            "dni_nie": "55556666E",
            "email": "activo@example.com",
        },
    )
    client.post(
        "/empleados/guardar",
        data={
            "empleado_id": "",
            "nombre_completo": "De Baja Oculto",
            "dni_nie": "77778888F",
            "email": "baja2@example.com",
        },
    )
    empleado_id = _buscar_empleado_por_dni("77778888F")["id"]
    client.post(f"/empleados/{empleado_id}/baja")

    respuesta_activos = client.get("/empleados")
    assert "Activo Visible" in respuesta_activos.text
    assert "De Baja Oculto" not in respuesta_activos.text

    respuesta_todos = client.get("/empleados?mostrar_baja=1")
    assert "Activo Visible" in respuesta_todos.text
    assert "De Baja Oculto" in respuesta_todos.text
