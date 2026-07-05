import re
import sqlite3
from pathlib import Path

NIF_EMPRESA_PATTERN = re.compile(r"^[A-Z]\d{7}[0-9A-Z]$")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nominas.db"

CAMPOS_EMPLEADO = {"nombre_completo", "dni_nie", "email", "activo", "fecha_alta", "fecha_baja"}

# NIF de la primera empresa del cliente, la que ya usa pdf_parser.py como ancla.
# La migración de envios_log antiguos (sin empresa_id) vincula a esta empresa
# todos los envíos ya existentes, porque hasta ahora era la única empresa real.
NIF_MEDIFORM_PLUS = "B82827635"
NOMBRE_MEDIFORM_PLUS = "MEDIFORM PLUS S.L."

SCHEMA = """
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    nif TEXT NOT NULL UNIQUE,
    activa INTEGER NOT NULL DEFAULT 1
);

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
    empresa_id INTEGER NOT NULL,
    email_destino TEXT NOT NULL,
    email_produccion TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('enviado', 'error', 'omitido')),
    detalle TEXT,
    FOREIGN KEY (empleado_id) REFERENCES empleados(id),
    FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);
"""


def _migrar_envios_log_email_produccion(conn: sqlite3.Connection) -> None:
    """Añade columnas nuevas a bases de datos creadas antes de que existieran
    (CREATE TABLE IF NOT EXISTS no altera tablas ya existentes)."""
    columnas = {fila["name"] for fila in conn.execute("PRAGMA table_info(envios_log)")}
    if "email_produccion" not in columnas:
        conn.execute("ALTER TABLE envios_log ADD COLUMN email_produccion TEXT")


def _migrar_empleados_quitar_empresa(conn: sqlite3.Connection) -> None:
    """Revierte `empleados` a UNIQUE(dni_nie) global, quitando `empresa_id`.

    Un DNI identifica a una persona física de forma única a nivel nacional: nunca puede
    haber dos empleados distintos con el mismo DNI, ni siquiera en empresas distintas.
    El caso real que motivó empresa_id en su día (una misma persona cobrando de varias
    empresas del cliente) se modela como "una persona, varios envíos" (empresa_id vive
    en envios_log), no como "varios empleados".

    SQLite no permite quitar una restricción UNIQUE con ALTER TABLE, así que hay que
    recrear la tabla.
    """
    columnas = {fila["name"] for fila in conn.execute("PRAGMA table_info(empleados)")}
    if "empresa_id" not in columnas:
        return  # ya revertido (o nunca llegó a tener empresa_id)

    total_antes = conn.execute("SELECT COUNT(*) AS n FROM empleados").fetchone()["n"]

    duplicados = conn.execute(
        "SELECT dni_nie, COUNT(*) AS n FROM empleados GROUP BY dni_nie HAVING COUNT(*) > 1"
    ).fetchall()
    if duplicados:
        dnis = ", ".join(f"{fila['dni_nie']} ({fila['n']} veces)" for fila in duplicados)
        raise RuntimeError(
            f"No se puede revertir empleados a DNI único global: hay DNIs duplicados entre "
            f"empresas distintas ({dnis}). Resuélvelo a mano antes de continuar."
        )

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE empleados_nuevo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_completo TEXT NOT NULL,
                dni_nie TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,
                fecha_alta TEXT NOT NULL,
                fecha_baja TEXT
            )
            """
        )

        conn.execute(
            """
            INSERT INTO empleados_nuevo (id, nombre_completo, dni_nie, email, activo, fecha_alta, fecha_baja)
            SELECT id, nombre_completo, dni_nie, email, activo, fecha_alta, fecha_baja FROM empleados
            """
        )

        total_despues = conn.execute("SELECT COUNT(*) AS n FROM empleados_nuevo").fetchone()["n"]
        if total_despues != total_antes:
            raise RuntimeError(
                f"Migración de empleados abortada: {total_antes} filas antes, {total_despues} después. "
                "No se ha modificado nada."
            )

        conn.execute("DROP TABLE empleados")
        conn.execute("ALTER TABLE empleados_nuevo RENAME TO empleados")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrar_envios_log_empresa(conn: sqlite3.Connection) -> None:
    """Añade `empresa_id` (NOT NULL) a `envios_log`, vinculando los envíos ya existentes
    a MEDIFORM PLUS S.L. (la única empresa real hasta ahora).

    obtener_envio_previo() filtra por empresa_id para que un envío de MEDIFORM PLUS S.L.
    nunca marque como "ya enviado este mes" la nómina de otra empresa de la misma persona.
    """
    columnas = {fila["name"] for fila in conn.execute("PRAGMA table_info(envios_log)")}
    if "empresa_id" in columnas:
        return  # ya migrado

    total_antes = conn.execute("SELECT COUNT(*) AS n FROM envios_log").fetchone()["n"]

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        empresa = conn.execute("SELECT id FROM empresas WHERE nif = ?", (NIF_MEDIFORM_PLUS,)).fetchone()
        if empresa is None:
            cursor = conn.execute(
                "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)",
                (NOMBRE_MEDIFORM_PLUS, NIF_MEDIFORM_PLUS),
            )
            empresa_id = cursor.lastrowid
        else:
            empresa_id = empresa["id"]

        conn.execute(
            """
            CREATE TABLE envios_log_nuevo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_hora TEXT NOT NULL,
                mes_nomina TEXT NOT NULL,
                empleado_id INTEGER NOT NULL,
                empresa_id INTEGER NOT NULL,
                email_destino TEXT NOT NULL,
                email_produccion TEXT,
                estado TEXT NOT NULL CHECK (estado IN ('enviado', 'error', 'omitido')),
                detalle TEXT,
                FOREIGN KEY (empleado_id) REFERENCES empleados(id),
                FOREIGN KEY (empresa_id) REFERENCES empresas(id)
            )
            """
        )

        conn.execute(
            """
            INSERT INTO envios_log_nuevo
                (id, fecha_hora, mes_nomina, empleado_id, empresa_id, email_destino, email_produccion, estado, detalle)
            SELECT id, fecha_hora, mes_nomina, empleado_id, ?, email_destino, email_produccion, estado, detalle
            FROM envios_log
            """,
            (empresa_id,),
        )

        total_despues = conn.execute("SELECT COUNT(*) AS n FROM envios_log_nuevo").fetchone()["n"]
        if total_despues != total_antes:
            raise RuntimeError(
                f"Migración de envios_log abortada: {total_antes} filas antes, {total_despues} después. "
                "No se ha modificado nada."
            )

        conn.execute("DROP TABLE envios_log")
        conn.execute("ALTER TABLE envios_log_nuevo RENAME TO envios_log")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrar_envios_log_email_produccion(conn)
    _migrar_empleados_quitar_empresa(conn)
    _migrar_envios_log_empresa(conn)
    conn.commit()


def get_connection(db_path=DB_PATH) -> sqlite3.Connection:
    """Abre la conexión y deja el esquema al día (tablas + migraciones) antes de devolverla,
    para que cualquier script que solo importe app.db funcione sobre una BD nueva o antigua
    sin tener que acordarse de llamar a init_db() aparte."""
    if db_path != ":memory:":
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def obtener_empresa_por_nif(conn: sqlite3.Connection, nif: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM empresas WHERE nif = ?", (nif,)).fetchone()


def obtener_empresa(conn: sqlite3.Connection, empresa_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()


def listar_empresas(conn: sqlite3.Connection, solo_activas: bool = False) -> list[sqlite3.Row]:
    query = "SELECT * FROM empresas"
    if solo_activas:
        query += " WHERE activa = 1"
    query += " ORDER BY nombre"
    return conn.execute(query).fetchall()


def crear_empresa(conn: sqlite3.Connection, nombre: str, nif: str, activa: bool = True) -> int:
    nombre = nombre.strip()
    nif_normalizado = nif.strip().upper().replace(" ", "")
    if not NIF_EMPRESA_PATTERN.match(nif_normalizado):
        raise ValueError(f"NIF con formato inválido: '{nif}'")

    cursor = conn.execute(
        "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, ?)",
        (nombre, nif_normalizado, 1 if activa else 0),
    )
    conn.commit()
    return cursor.lastrowid


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


def reactivar_empleado(conn: sqlite3.Connection, empleado_id: int) -> None:
    """Deshace una baja: vuelve a marcar al empleado como activo y borra su fecha_baja."""
    conn.execute(
        "UPDATE empleados SET activo = 1, fecha_baja = NULL WHERE id = ?",
        (empleado_id,),
    )
    conn.commit()


def registrar_envio(
    conn: sqlite3.Connection,
    fecha_hora: str,
    mes_nomina: str,
    empleado_id: int,
    empresa_id: int,
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
        INSERT INTO envios_log
            (fecha_hora, mes_nomina, empleado_id, empresa_id, email_destino, email_produccion, estado, detalle)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (fecha_hora, mes_nomina, empleado_id, empresa_id, email_destino, email_produccion, estado, detalle),
    )
    conn.commit()
    return cursor.lastrowid


def obtener_envio_previo(conn: sqlite3.Connection, empleado_id: int, empresa_id: int, mes_nomina: str) -> sqlite3.Row | None:
    """Devuelve el envío 'enviado' más reciente para este empleado, empresa y mes, o None si no hubo ninguno.

    Se filtra también por empresa_id porque el mismo empleado puede recibir nóminas de más
    de una empresa del cliente el mismo mes: son envíos independientes, uno no debe marcar
    como "ya enviado" al otro.

    Puramente informativo: no bloquea ni impide un reenvío, solo permite avisar de que ya existe uno.
    """
    return conn.execute(
        """
        SELECT * FROM envios_log
        WHERE empleado_id = ? AND empresa_id = ? AND mes_nomina = ? AND estado = 'enviado'
        ORDER BY fecha_hora DESC
        LIMIT 1
        """,
        (empleado_id, empresa_id, mes_nomina),
    ).fetchone()
