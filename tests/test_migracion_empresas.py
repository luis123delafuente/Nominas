import sqlite3

import pytest

from app.db import NIF_MEDIFORM_PLUS, NOMBRE_MEDIFORM_PLUS, get_connection

TOTAL_EMPLEADOS = 29
TOTAL_ENVIOS = 5


def _crear_bd_estado_fase_8_1(ruta) -> None:
    """Reproduce el esquema tal como estaba antes de esta corrección (Fase 8.1):
    empleados CON empresa_id (UNIQUE compuesto), envios_log SIN empresa_id.
    Con datos de ejemplo, para probar la migración sin tocar la base de datos real.
    """
    conn = sqlite3.connect(ruta)
    conn.execute(
        """
        CREATE TABLE empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nif TEXT NOT NULL UNIQUE,
            activa INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    empresa_id = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", (NOMBRE_MEDIFORM_PLUS, NIF_MEDIFORM_PLUS)
    ).lastrowid

    conn.execute(
        """
        CREATE TABLE empleados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            nombre_completo TEXT NOT NULL,
            dni_nie TEXT NOT NULL,
            email TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_alta TEXT NOT NULL,
            fecha_baja TEXT,
            UNIQUE (empresa_id, dni_nie),
            FOREIGN KEY (empresa_id) REFERENCES empresas(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE envios_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            mes_nomina TEXT NOT NULL,
            empleado_id INTEGER NOT NULL,
            email_destino TEXT NOT NULL,
            email_produccion TEXT,
            estado TEXT NOT NULL CHECK (estado IN ('enviado', 'error', 'omitido')),
            detalle TEXT,
            FOREIGN KEY (empleado_id) REFERENCES empleados(id)
        )
        """
    )

    for i in range(TOTAL_EMPLEADOS):
        conn.execute(
            "INSERT INTO empleados (empresa_id, nombre_completo, dni_nie, email, fecha_alta) VALUES (?, ?, ?, ?, ?)",
            (empresa_id, f"Empleado {i}", f"{10000000 + i}A", f"empleado{i}@example.com", "2025-01-01"),
        )
    for i in range(TOTAL_ENVIOS):
        conn.execute(
            "INSERT INTO envios_log (fecha_hora, mes_nomina, empleado_id, email_destino, estado) VALUES (?, ?, ?, ?, ?)",
            (f"2026-07-0{i + 1}T10:00:00", "2026-06", (i % TOTAL_EMPLEADOS) + 1, f"empleado{i}@example.com", "enviado"),
        )
    conn.commit()
    conn.close()


def test_migracion_revierte_empleados_a_dni_unico_global_sin_perder_ninguno(tmp_path):
    ruta_db = tmp_path / "fase_8_1.db"
    _crear_bd_estado_fase_8_1(ruta_db)

    conn = get_connection(ruta_db)  # get_connection ya dispara init_db() -> las migraciones

    columnas = {fila["name"] for fila in conn.execute("PRAGMA table_info(empleados)")}
    assert "empresa_id" not in columnas  # ya no vive en empleados

    empleados = conn.execute("SELECT * FROM empleados").fetchall()
    assert len(empleados) == TOTAL_EMPLEADOS  # ninguno perdido

    conn.close()


def test_migracion_empleados_dni_es_unico_global_tras_revertir(tmp_path):
    ruta_db = tmp_path / "fase_8_1.db"
    _crear_bd_estado_fase_8_1(ruta_db)

    conn = get_connection(ruta_db)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO empleados (nombre_completo, dni_nie, email, fecha_alta) VALUES (?, ?, ?, ?)",
            ("Duplicado", "10000000A", "dup@example.com", "2025-01-01"),
        )

    conn.close()


def test_migracion_anade_empresa_id_a_envios_log_vinculado_a_mediform_plus(tmp_path):
    ruta_db = tmp_path / "fase_8_1.db"
    _crear_bd_estado_fase_8_1(ruta_db)

    conn = get_connection(ruta_db)

    empresa = conn.execute("SELECT * FROM empresas WHERE nif = ?", (NIF_MEDIFORM_PLUS,)).fetchone()
    assert empresa is not None

    envios = conn.execute("SELECT * FROM envios_log").fetchall()
    assert len(envios) == TOTAL_ENVIOS  # ninguno perdido
    assert all(e["empresa_id"] == empresa["id"] for e in envios)

    conn.close()


def test_migracion_conserva_los_ids_y_no_deja_huerfanos_en_envios_log(tmp_path):
    ruta_db = tmp_path / "fase_8_1.db"
    _crear_bd_estado_fase_8_1(ruta_db)

    conn = get_connection(ruta_db)

    envios = conn.execute("SELECT * FROM envios_log ORDER BY id").fetchall()
    assert [e["id"] for e in envios] == list(range(1, TOTAL_ENVIOS + 1))  # los ids no cambian

    huerfanos_empleado = conn.execute(
        """
        SELECT e.id FROM envios_log e
        LEFT JOIN empleados emp ON e.empleado_id = emp.id
        WHERE emp.id IS NULL
        """
    ).fetchall()
    assert huerfanos_empleado == []

    huerfanos_empresa = conn.execute(
        """
        SELECT e.id FROM envios_log e
        LEFT JOIN empresas emp ON e.empresa_id = emp.id
        WHERE emp.id IS NULL
        """
    ).fetchall()
    assert huerfanos_empresa == []

    conn.close()


def test_migracion_es_idempotente_si_se_ejecuta_dos_veces(tmp_path):
    ruta_db = tmp_path / "fase_8_1.db"
    _crear_bd_estado_fase_8_1(ruta_db)

    conn = get_connection(ruta_db)
    conn.close()

    conn = get_connection(ruta_db)  # segunda apertura: las migraciones ya se aplicaron, no deben repetirse
    empleados = conn.execute("SELECT * FROM empleados").fetchall()
    assert len(empleados) == TOTAL_EMPLEADOS

    envios = conn.execute("SELECT * FROM envios_log").fetchall()
    assert len(envios) == TOTAL_ENVIOS

    empresas = conn.execute("SELECT * FROM empresas WHERE nif = ?", (NIF_MEDIFORM_PLUS,)).fetchall()
    assert len(empresas) == 1  # no se duplica la empresa
    conn.close()
