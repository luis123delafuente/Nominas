import sqlite3

import pytest

from app.db import (
    actualizar_empleado,
    actualizar_empresa,
    actualizar_iban_bic_cuenta,
    actualizar_iban_empleado,
    crear_cuenta_bancaria,
    crear_empleado,
    crear_empresa,
    dar_baja_empleado,
    descifrar_cuenta_bancaria,
    descifrar_credenciales_smtp,
    get_connection,
    guardar_credenciales_smtp,
    init_db,
    listar_cuentas_bancarias,
    listar_empleados,
    marcar_cuenta_predeterminada,
    obtener_credenciales_smtp,
    obtener_cuenta_predeterminada,
    obtener_empleado,
    obtener_empresa,
    obtener_envio_previo,
    obtener_iban_empleado,
    reactivar_empleado,
    registrar_envio,
)

IBAN_VALIDO_1 = "ES9121000418450200051332"
IBAN_VALIDO_2 = "ES7620770024003102575766"
BIC_VALIDO = "CAIXESBBXXX"


@pytest.fixture
def conn():
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def ruta_clave(tmp_path):
    """Clave de cifrado en un directorio temporal — nunca la real de data/,
    para no dejar rastro en el proyecto ni depender de su estado."""
    return tmp_path / "clave_cifrado.key"


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


def test_actualizar_empresa(conn):
    empresa_id = crear_empresa(conn, "Nombre Viejo S.L.", "B11111111")

    actualizar_empresa(conn, empresa_id, nombre="Nombre Nuevo S.L.")

    empresa = obtener_empresa(conn, empresa_id)
    assert empresa["nombre"] == "Nombre Nuevo S.L."
    assert empresa["nif"] == "B11111111"  # no tocado


def test_actualizar_empresa_normaliza_y_valida_el_nif(conn):
    empresa_id = crear_empresa(conn, "Empresa", "B22222222")

    actualizar_empresa(conn, empresa_id, nif=" b33333333 ")
    assert obtener_empresa(conn, empresa_id)["nif"] == "B33333333"

    with pytest.raises(ValueError):
        actualizar_empresa(conn, empresa_id, nif="NOESUNNIF")


def test_actualizar_empresa_puede_desactivarla_y_reactivarla(conn):
    empresa_id = crear_empresa(conn, "Empresa", "B44444444")

    actualizar_empresa(conn, empresa_id, activa=False)
    assert obtener_empresa(conn, empresa_id)["activa"] == 0

    actualizar_empresa(conn, empresa_id, activa=True)
    assert obtener_empresa(conn, empresa_id)["activa"] == 1


def test_actualizar_empresa_rechaza_campos_no_permitidos(conn):
    empresa_id = crear_empresa(conn, "Empresa", "B55555555")

    with pytest.raises(ValueError):
        actualizar_empresa(conn, empresa_id, id=999)


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


# --- IBAN de empleado ---------------------------------------------------------------


def test_guardar_y_leer_iban_de_empleado_va_cifrado_en_la_columna(conn, ruta_clave):
    empleado_id = crear_empleado(conn, "Con Iban", "10101010A", "coniban@example.com", "2025-01-01")

    actualizar_iban_empleado(conn, empleado_id, "  es91 2100 0418 4502 0005 1332  ", ruta_clave=ruta_clave)

    fila = conn.execute("SELECT iban_cifrado FROM empleados WHERE id = ?", (empleado_id,)).fetchone()
    assert fila["iban_cifrado"] != IBAN_VALIDO_1  # nunca en claro en la base de datos
    assert obtener_iban_empleado(conn, empleado_id, ruta_clave=ruta_clave) == IBAN_VALIDO_1


def test_iban_de_empleado_con_checksum_invalido_se_rechaza(conn, ruta_clave):
    empleado_id = crear_empleado(conn, "Con Iban Malo", "20202020B", "malo@example.com", "2025-01-01")

    with pytest.raises(ValueError):
        actualizar_iban_empleado(conn, empleado_id, "ES9121000418450200051333", ruta_clave=ruta_clave)


def test_borrar_iban_de_empleado(conn, ruta_clave):
    empleado_id = crear_empleado(conn, "Para Borrar Iban", "30303030C", "borrar@example.com", "2025-01-01")
    actualizar_iban_empleado(conn, empleado_id, IBAN_VALIDO_1, ruta_clave=ruta_clave)

    actualizar_iban_empleado(conn, empleado_id, None, ruta_clave=ruta_clave)

    assert obtener_iban_empleado(conn, empleado_id, ruta_clave=ruta_clave) is None


def test_empleado_sin_iban_devuelve_none(conn, ruta_clave):
    empleado_id = crear_empleado(conn, "Sin Iban", "40404040D", "siniban@example.com", "2025-01-01")

    assert obtener_iban_empleado(conn, empleado_id, ruta_clave=ruta_clave) is None


# --- Cuentas bancarias de empresa ----------------------------------------------------


def test_crear_cuenta_bancaria_la_guarda_cifrada(conn, empresa_id, ruta_clave):
    cuenta_id = crear_cuenta_bancaria(
        conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, alias="Cuenta principal", ruta_clave=ruta_clave
    )

    fila = conn.execute("SELECT * FROM cuentas_bancarias WHERE id = ?", (cuenta_id,)).fetchone()
    assert fila["iban_cifrado"] != IBAN_VALIDO_1
    assert fila["bic_cifrado"] != BIC_VALIDO

    descifrada = descifrar_cuenta_bancaria(fila, ruta_clave=ruta_clave)
    assert descifrada["iban"] == IBAN_VALIDO_1
    assert descifrada["bic"] == BIC_VALIDO
    assert descifrada["alias"] == "Cuenta principal"


def test_crear_cuenta_bancaria_con_iban_checksum_invalido_se_rechaza(conn, empresa_id, ruta_clave):
    with pytest.raises(ValueError, match="dígito de control"):
        crear_cuenta_bancaria(conn, empresa_id, "ES9121000418450200051333", BIC_VALIDO, ruta_clave=ruta_clave)


def test_crear_cuenta_bancaria_con_bic_invalido_se_rechaza(conn, empresa_id, ruta_clave):
    with pytest.raises(ValueError, match="formato inválido"):
        crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_1, "NOESUNBIC", ruta_clave=ruta_clave)


def test_primera_cuenta_de_una_empresa_es_predeterminada_automaticamente(conn, empresa_id, ruta_clave):
    crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, ruta_clave=ruta_clave)

    predeterminada = obtener_cuenta_predeterminada(conn, empresa_id)
    assert predeterminada is not None


def test_segunda_cuenta_no_desplaza_la_predeterminada_salvo_que_se_pida(conn, empresa_id, ruta_clave):
    primera_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, ruta_clave=ruta_clave)
    crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_2, BIC_VALIDO, ruta_clave=ruta_clave)

    predeterminada = obtener_cuenta_predeterminada(conn, empresa_id)
    assert predeterminada["id"] == primera_id


def test_marcar_cuenta_predeterminada_desmarca_la_anterior(conn, empresa_id, ruta_clave):
    primera_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, ruta_clave=ruta_clave)
    segunda_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_2, BIC_VALIDO, ruta_clave=ruta_clave)

    marcar_cuenta_predeterminada(conn, empresa_id, segunda_id)

    predeterminada = obtener_cuenta_predeterminada(conn, empresa_id)
    assert predeterminada["id"] == segunda_id

    primera = conn.execute("SELECT predeterminada FROM cuentas_bancarias WHERE id = ?", (primera_id,)).fetchone()
    assert primera["predeterminada"] == 0


def test_indice_unico_impide_dos_cuentas_predeterminadas_a_la_vez(conn, empresa_id, ruta_clave):
    crear_cuenta_bancaria(
        conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, predeterminada=True, ruta_clave=ruta_clave
    )

    with pytest.raises(sqlite3.IntegrityError):
        # Se salta a propósito crear_cuenta_bancaria() (que desmarcaría la anterior)
        # para comprobar que la base de datos también aplica la regla por sí sola.
        conn.execute(
            "INSERT INTO cuentas_bancarias (empresa_id, iban_cifrado, bic_cifrado, predeterminada) "
            "VALUES (?, 'x', 'y', 1)",
            (empresa_id,),
        )


def test_listar_cuentas_bancarias_ordena_la_predeterminada_primero(conn, empresa_id, ruta_clave):
    primera_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, ruta_clave=ruta_clave)
    segunda_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_2, BIC_VALIDO, ruta_clave=ruta_clave)
    marcar_cuenta_predeterminada(conn, empresa_id, segunda_id)

    cuentas = listar_cuentas_bancarias(conn, empresa_id)

    assert [c["id"] for c in cuentas] == [segunda_id, primera_id]


def test_actualizar_iban_bic_cuenta(conn, empresa_id, ruta_clave):
    cuenta_id = crear_cuenta_bancaria(conn, empresa_id, IBAN_VALIDO_1, BIC_VALIDO, ruta_clave=ruta_clave)

    actualizar_iban_bic_cuenta(conn, cuenta_id, IBAN_VALIDO_2, "BSABESBBXXX", ruta_clave=ruta_clave)

    fila = conn.execute("SELECT * FROM cuentas_bancarias WHERE id = ?", (cuenta_id,)).fetchone()
    descifrada = descifrar_cuenta_bancaria(fila, ruta_clave=ruta_clave)
    assert descifrada["iban"] == IBAN_VALIDO_2
    assert descifrada["bic"] == "BSABESBBXXX"


# --- Credenciales SMTP: guardado cifrado, upsert por empresa, validación --------------


def test_guardar_credenciales_smtp_la_guarda_cifrada(conn, empresa_id, ruta_clave):
    guardar_credenciales_smtp(
        conn, empresa_id, "smtp.gmail.com", 587, "empresa@gmail.com", "contraseña-secreta", ruta_clave=ruta_clave
    )

    fila = obtener_credenciales_smtp(conn, empresa_id)
    assert fila["host"] == "smtp.gmail.com"
    assert fila["puerto"] == 587
    assert fila["usuario"] == "empresa@gmail.com"
    assert fila["password_cifrado"] != "contraseña-secreta"
    assert "contraseña-secreta" not in fila["password_cifrado"]

    descifrada = descifrar_credenciales_smtp(fila, ruta_clave=ruta_clave)
    assert descifrada["password"] == "contraseña-secreta"


def test_guardar_credenciales_smtp_es_upsert_una_fila_por_empresa(conn, empresa_id, ruta_clave):
    guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "vieja@gmail.com", "clave-vieja", ruta_clave=ruta_clave)
    guardar_credenciales_smtp(
        conn, empresa_id, "smtp.office365.com", 587, "nueva@outlook.com", "clave-nueva", ruta_clave=ruta_clave
    )

    total = conn.execute("SELECT COUNT(*) AS n FROM credenciales_smtp WHERE empresa_id = ?", (empresa_id,)).fetchone()["n"]
    assert total == 1

    fila = obtener_credenciales_smtp(conn, empresa_id)
    assert fila["host"] == "smtp.office365.com"
    assert fila["usuario"] == "nueva@outlook.com"
    assert descifrar_credenciales_smtp(fila, ruta_clave=ruta_clave)["password"] == "clave-nueva"


def test_guardar_credenciales_smtp_rechaza_puerto_fuera_de_rango(conn, empresa_id, ruta_clave):
    with pytest.raises(ValueError):
        guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 99999, "a@gmail.com", "clave", ruta_clave=ruta_clave)


def test_guardar_credenciales_smtp_rechaza_usuario_sin_arroba(conn, empresa_id, ruta_clave):
    with pytest.raises(ValueError):
        guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "no-es-un-email", "clave", ruta_clave=ruta_clave)


def test_guardar_credenciales_smtp_rechaza_password_vacia(conn, empresa_id, ruta_clave):
    with pytest.raises(ValueError):
        guardar_credenciales_smtp(conn, empresa_id, "smtp.gmail.com", 587, "a@gmail.com", "", ruta_clave=ruta_clave)


def test_obtener_credenciales_smtp_inexistente_devuelve_none(conn, empresa_id):
    assert obtener_credenciales_smtp(conn, empresa_id) is None
