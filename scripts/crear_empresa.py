"""Script de un solo uso: da de alta una empresa nueva en data/nominas.db.

Uso:
    ./venv/bin/python3 scripts/crear_empresa.py "Nombre de la Empresa S.L." B12345678
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import crear_empresa, get_connection


def main(nombre: str, nif: str) -> None:
    conn = get_connection()
    try:
        empresa_id = crear_empresa(conn, nombre, nif)
    except ValueError as exc:
        print(f"Error: {exc}")
        return
    except sqlite3.IntegrityError:
        print(f"Ya existe una empresa con el NIF {nif.strip().upper()}. No se ha creado nada.")
        return
    finally:
        conn.close()

    print(f"Empresa creada correctamente: {nombre} (NIF {nif.strip().upper()}), id={empresa_id}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Uso: ./venv/bin/python3 scripts/crear_empresa.py "Nombre de la Empresa S.L." NIF')
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])
