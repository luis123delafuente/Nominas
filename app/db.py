import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nominas.db"

CAMPOS_EMPLEADO = {"nombre_completo", "dni_nie", "email", "activo", "fecha_alta", "fecha_baja"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS empleados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    dni_nie TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    fecha_alta TEXT NOT NULL,
    fecha_baja TEXT
);

CREATE TABLE IF NOT EXISTS envios_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    mes_nomina TEXT NOT NULL,
    empleado_id INTEGER NOT NULL,
    email_destino TEXT NOT NULL,
    email_produccion TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('enviado', 'error', 'omitido')),
    detalle TEXT,
    FOREIGN KEY (empleado_id) REFERENCES empleados(id)
);
"""


def get_connection(db_path=DB_PATH) -> sqlite3.Connection:
    if db_path != ":memory:":
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrar_envios_log(conn: sqlite3.Connection) -> None:
    """Añade columnas nuevas a bases de datos creadas antes de que existieran
    (CREATE TABLE IF NOT EXISTS no altera tablas ya existentes)."""
    columnas = {fila["name"] for fila in conn.execute("PRAGMA table_info(envios_log)")}
    if "email_produccion" not in columnas:
        conn.execute("ALTER TABLE envios_log ADD COLUMN email_produccion TEXT")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrar_envios_log(conn)
    conn.commit()


def crear_empleado(conn: sqlite3.Connection, nombre_completo: str, dni_nie: str, email: str, fecha_alta: str) -> int:
    cursor = conn.execute(
        "INSERT INTO empleados (nombre_completo, dni_nie, email, fecha_alta) VALUES (?, ?, ?, ?)",
        (nombre_completo.strip(), dni_nie.strip().upper(), email.strip(), fecha_alta),
    )
    conn.commit()
    return cursor.lastrowid


def obtener_empleado(conn: sqlite3.Connection, empleado_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM empleados WHERE id = ?", (empleado_id,)).fetchone()


def listar_empleados(conn: sqlite3.Connection, solo_activos: bool = False) -> list[sqlite3.Row]:
    query = "SELECT * FROM empleados"
    if solo_activos:
        query += " WHERE activo = 1"
    query += " ORDER BY nombre_completo"
    return conn.execute(query).fetchall()


def actualizar_empleado(conn: sqlite3.Connection, empleado_id: int, **campos) -> None:
    if not campos:
        return
    if not set(campos).issubset(CAMPOS_EMPLEADO):
        raise ValueError(f"Campos no permitidos: {set(campos) - CAMPOS_EMPLEADO}")

    columnas = ", ".join(f"{campo} = ?" for campo in campos)
    valores = [*campos.values(), empleado_id]
    conn.execute(f"UPDATE empleados SET {columnas} WHERE id = ?", valores)
    conn.commit()


def dar_baja_empleado(conn: sqlite3.Connection, empleado_id: int, fecha_baja: str) -> None:
    conn.execute(
        "UPDATE empleados SET activo = 0, fecha_baja = ? WHERE id = ?",
        (fecha_baja, empleado_id),
    )
    conn.commit()


def registrar_envio(
    conn: sqlite3.Connection,
    fecha_hora: str,
    mes_nomina: str,
    empleado_id: int,
    email_destino: str,
    estado: str,
    detalle: str | None = None,
    email_produccion: str | None = None,
) -> int:
    """Registra un envío en el histórico. `email_destino` es a quién se envió de verdad;
    `email_produccion` solo debe rellenarse cuando el envío fue en modo prueba, para que
    quede constancia de a quién le habría correspondido en producción."""
    cursor = conn.execute(
        """
        INSERT INTO envios_log (fecha_hora, mes_nomina, empleado_id, email_destino, email_produccion, estado, detalle)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (fecha_hora, mes_nomina, empleado_id, email_destino, email_produccion, estado, detalle),
    )
    conn.commit()
    return cursor.lastrowid
