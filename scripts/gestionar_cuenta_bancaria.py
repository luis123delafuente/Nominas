"""Script de un solo uso: alta, edición, listado y cuenta predeterminada de las
cuentas bancarias de una empresa (usadas para generar el fichero SEPA).

Uso:
    ./venv/bin/python3 scripts/gestionar_cuenta_bancaria.py listar B82827635
    ./venv/bin/python3 scripts/gestionar_cuenta_bancaria.py alta B82827635 \\
        ES9121000418450200051332 CAIXESBBXXX --alias "Cuenta nómina"
    ./venv/bin/python3 scripts/gestionar_cuenta_bancaria.py editar 3 \\
        ES7620770024003102575766 BSABESBBXXX
    ./venv/bin/python3 scripts/gestionar_cuenta_bancaria.py predeterminada B82827635 3
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import (
    actualizar_iban_bic_cuenta,
    crear_cuenta_bancaria,
    descifrar_cuenta_bancaria,
    get_connection,
    listar_cuentas_bancarias,
    marcar_cuenta_predeterminada,
    obtener_empresa_por_nif,
)


def _empresa_por_nif_o_falla(conn, nif: str):
    empresa = obtener_empresa_por_nif(conn, nif.strip().upper())
    if empresa is None:
        print(f"No existe ninguna empresa con NIF {nif}. Dala de alta antes con scripts/crear_empresa.py.")
        return None
    return empresa


def listar(nif: str) -> None:
    conn = get_connection()
    try:
        empresa = _empresa_por_nif_o_falla(conn, nif)
        if empresa is None:
            return
        cuentas = listar_cuentas_bancarias(conn, empresa["id"])
        if not cuentas:
            print(f"{empresa['nombre']} no tiene ninguna cuenta bancaria registrada.")
            return
        print(f"Cuentas de {empresa['nombre']}:")
        for cuenta in cuentas:
            datos = descifrar_cuenta_bancaria(cuenta)
            marca = " [PREDETERMINADA]" if cuenta["predeterminada"] else ""
            estado = "" if cuenta["activa"] else " (inactiva)"
            print(f"  id={cuenta['id']} {datos['alias'] or '(sin alias)'} — {datos['iban']} / {datos['bic']}{marca}{estado}")
    finally:
        conn.close()


def alta(nif: str, iban: str, bic: str, alias: str | None) -> None:
    conn = get_connection()
    try:
        empresa = _empresa_por_nif_o_falla(conn, nif)
        if empresa is None:
            return
        try:
            cuenta_id = crear_cuenta_bancaria(conn, empresa["id"], iban, bic, alias=alias)
        except ValueError as exc:
            print(f"Error: {exc}")
            return
        print(f"Cuenta creada correctamente para {empresa['nombre']}, id={cuenta_id}.")
    finally:
        conn.close()


def editar(cuenta_id: int, iban: str, bic: str) -> None:
    conn = get_connection()
    try:
        try:
            actualizar_iban_bic_cuenta(conn, cuenta_id, iban, bic)
        except ValueError as exc:
            print(f"Error: {exc}")
            return
        print(f"Cuenta {cuenta_id} actualizada correctamente.")
    finally:
        conn.close()


def predeterminada(nif: str, cuenta_id: int) -> None:
    conn = get_connection()
    try:
        empresa = _empresa_por_nif_o_falla(conn, nif)
        if empresa is None:
            return
        try:
            marcar_cuenta_predeterminada(conn, empresa["id"], cuenta_id)
        except ValueError as exc:
            print(f"Error: {exc}")
            return
        print(f"Cuenta {cuenta_id} marcada como predeterminada para {empresa['nombre']}.")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gestiona las cuentas bancarias de una empresa.")
    subparsers = parser.add_subparsers(dest="accion", required=True)

    p_listar = subparsers.add_parser("listar")
    p_listar.add_argument("nif")

    p_alta = subparsers.add_parser("alta")
    p_alta.add_argument("nif")
    p_alta.add_argument("iban")
    p_alta.add_argument("bic")
    p_alta.add_argument("--alias")

    p_editar = subparsers.add_parser("editar")
    p_editar.add_argument("cuenta_id", type=int)
    p_editar.add_argument("iban")
    p_editar.add_argument("bic")

    p_predet = subparsers.add_parser("predeterminada")
    p_predet.add_argument("nif")
    p_predet.add_argument("cuenta_id", type=int)

    args = parser.parse_args()

    try:
        if args.accion == "listar":
            listar(args.nif)
        elif args.accion == "alta":
            alta(args.nif, args.iban, args.bic, args.alias)
        elif args.accion == "editar":
            editar(args.cuenta_id, args.iban, args.bic)
        elif args.accion == "predeterminada":
            predeterminada(args.nif, args.cuenta_id)
    except sqlite3.IntegrityError as exc:
        print(f"Error de integridad en la base de datos: {exc}")
