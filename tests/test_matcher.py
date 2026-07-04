import pytest

from app.db import crear_empleado, get_connection, init_db, listar_empleados
from app.matcher import emparejar_nomina


@pytest.fixture
def empleados():
    conn = get_connection(":memory:")
    init_db(conn)
    crear_empleado(conn, "Nicolás Alcalde Lasaosa", "02349419S", "nicolas@example.com", "2025-01-01")
    crear_empleado(conn, "Ángela Cañas Iglesias", "50908836S", "angela@example.com", "2025-01-01")
    crear_empleado(conn, "Luis Francisco De La Fuente Ruiz", "02855714B", "luis@example.com", "2025-01-01")
    crear_empleado(conn, "Sonia Perez Fernandez", "99999999R", "sonia.pf@example.com", "2025-01-01")
    crear_empleado(conn, "Sonia Perez Morante", "16065449H", "sonia.pm@example.com", "2025-01-01")
    yield listar_empleados(conn)
    conn.close()


# --- Match primario por DNI (caso normal: nombre y DNI cuadran) ---


def test_dni_exacto_distingue_dos_empleadas_con_mismo_nombre_y_primer_apellido(empleados):
    resultado_fernandez = emparejar_nomina("PEREZ FERNANDEZ, SONIA", "99999999R", empleados)
    resultado_morante = emparejar_nomina("PEREZ MORANTE, SONIA", "16065449H", empleados)

    assert resultado_fernandez.metodo == "dni_exacto"
    assert resultado_fernandez.empleado["dni_nie"] == "99999999R"

    assert resultado_morante.metodo == "dni_exacto"
    assert resultado_morante.empleado["dni_nie"] == "16065449H"


def test_dni_exacto_con_nombre_truncado_por_ancho_de_columna(empleados):
    # El PDF trunca "LUIS FRANCISCO" a "LUIS", pero el DNI no engaña.
    resultado = emparejar_nomina("DE LA FUENTE RUIZ, LUIS", "02855714B", empleados)

    assert resultado.metodo == "dni_exacto"
    assert resultado.empleado["dni_nie"] == "02855714B"


# --- Alerta de seguridad: DNI coincide pero el nombre no cuadra ---


def test_dni_coincide_pero_nombre_muy_distinto_marca_alerta(empleados):
    # DNI de Nicolás, pero el nombre que trae esta nómina no se le parece nada
    # (p.ej. error de tecleo en la ficha o DNI mal extraído del PDF).
    resultado = emparejar_nomina("ZAPATERO GOMEZ, RODRIGO", "02349419S", empleados)

    assert resultado.metodo == "dni_con_alerta_nombre"
    assert resultado.empleado["dni_nie"] == "02349419S"
    assert resultado.score_nombre < 50


def test_dni_no_registrado_no_cae_a_fuzzy_por_nombre(empleados):
    # DNI con formato válido pero que no está en la BD: no se adivina por nombre.
    resultado = emparejar_nomina("PEREZ MORANTE, SONIA", "00000000T", empleados)

    assert resultado.metodo == "sin_match"
    assert resultado.empleado is None


# --- Fallback fuzzy por nombre: solo cuando no hay DNI extraído en esa nómina ---


def test_fallback_fuzzy_con_orden_de_apellidos_distinto_cuando_no_hay_dni(empleados):
    resultado = emparejar_nomina("ALCALDE LASAOSA, NICOLAS", None, empleados)

    assert resultado.metodo == "fuzzy_nombre"
    assert resultado.empleado["dni_nie"] == "02349419S"


def test_fallback_fuzzy_con_tildes_distintas_cuando_no_hay_dni(empleados):
    resultado = emparejar_nomina("CAÑAS IGLESIAS, ANGELA", None, empleados)

    assert resultado.metodo == "fuzzy_nombre"
    assert resultado.empleado["dni_nie"] == "50908836S"


def test_fallback_fuzzy_nombre_truncado_no_alcanza_el_umbral(empleados):
    # Sin DNI que desambigüe, el nombre truncado por sí solo no basta para un match automático.
    resultado = emparejar_nomina("DE LA FUENTE RUIZ, LUIS", None, empleados)

    assert resultado.metodo == "sin_match"
    assert resultado.empleado["dni_nie"] == "02855714B"  # se sugiere igualmente para revisión manual
    assert resultado.score_nombre > 0


def test_sin_dni_y_sin_coincidencia_de_nombre(empleados):
    resultado = emparejar_nomina("ZAPATERO GOMEZ, RODRIGO", None, empleados)

    assert resultado.metodo == "sin_match"
    assert resultado.score_nombre < 60


def test_lista_de_empleados_vacia():
    resultado = emparejar_nomina("CUALQUIERA, PERSONA", None, [])

    assert resultado.empleado is None
    assert resultado.metodo == "sin_match"
    assert resultado.score_nombre == 0.0
