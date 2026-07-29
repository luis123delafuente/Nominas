"""Script de un solo uso: edita el nombre, NIF o estado (activa/inactiva) de una empresa
ya existente en data/nominas.db.

Uso:
    ./venv/bin/python3 scripts/editar_empresa.py <id_empresa> --nombre "Nuevo Nombre S.L."
    ./venv/bin/python3 scripts/editar_empresa.py <id_empresa> --nif B12345678
    ./venv/bin/python3 scripts/editar_empresa.py <id_empresa> --inactiva
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import actualizar_empresa, get_connection, obtener_empresa


def main(empresa_id: int, nombre: str | None, nif: str | None, activa: bool | None) -> None:
    campos = {}
    if nombre is not None:
        campos["nombre"] = nombre
    if nif is not None:
        campos["nif"] = nif
    if activa is not None:
        campos["activa"] = activa

    if not campos:
        print("No se ha indicado ningún cambio (usa --nombre, --nif, --activa o --inactiva).")
        return

    conn = get_connection()
    try:
        if obtener_empresa(conn, empresa_id) is None:
            print(f"No existe ninguna empresa con id={empresa_id}.")
            return

        try:
            actualizar_empresa(conn, empresa_id, **campos)
        except ValueError as exc:
            print(f"Error: {exc}")
            return
        except sqlite3.IntegrityError:
            print("Ya existe otra empresa con ese NIF. No se ha modificado nada.")
            return

        empresa = obtener_empresa(conn, empresa_id)
    finally:
        conn.close()

    print(f"Empresa actualizada: {empresa['nombre']} (NIF {empresa['nif']}, activa={bool(empresa['activa'])})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Edita una empresa existente.")
    parser.add_argument("empresa_id", type=int)
    parser.add_argument("--nombre")
    parser.add_argument("--nif")
    grupo_estado = parser.add_mutually_exclusive_group()
    grupo_estado.add_argument("--activa", action="store_true", dest="activa", default=None)
    grupo_estado.add_argument("--inactiva", action="store_false", dest="activa", default=None)
    args = parser.parse_args()

    main(args.empresa_id, args.nombre, args.nif, args.activa)
