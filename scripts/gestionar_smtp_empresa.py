"""Script de un solo uso: alta/actualización y listado de las credenciales SMTP de
envío de una empresa (usadas para mandar las nóminas por email). Operación de
configuración inicial poco frecuente — no tiene pantalla dedicada en la app.

Antes de dar de alta hace falta generar una "contraseña de aplicación" en Gmail o en
Outlook/Office365 — ver DOCUMENTO_CONTRASENA_APLICACION.md para el paso a paso, pensado
para que lo siga un cliente sin conocimientos técnicos.

Uso:
    ./venv/bin/python3 scripts/gestionar_smtp_empresa.py alta B82827635 \\
        smtp.gmail.com 587 mediformplus@gmail.com
    (pedirá la contraseña de aplicación de forma interactiva, sin mostrarla en pantalla)

    ./venv/bin/python3 scripts/gestionar_smtp_empresa.py listar B82827635

Puertos habituales:
    Gmail:              smtp.gmail.com   587 (STARTTLS) o 465 (TLS implícito)
    Outlook/Office365:  smtp.office365.com   587 (STARTTLS)
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import (
    descifrar_credenciales_smtp,
    get_connection,
    guardar_credenciales_smtp,
    obtener_credenciales_smtp,
    obtener_empresa_por_nif,
)


def _empresa_por_nif_o_falla(conn, nif: str):
    empresa = obtener_empresa_por_nif(conn, nif.strip().upper())
    if empresa is None:
        print(f"No existe ninguna empresa con NIF {nif}. Dala de alta antes con scripts/crear_empresa.py.")
        return None
    return empresa


def alta(nif: str, host: str, puerto: int, usuario: str, password: str) -> None:
    conn = get_connection()
    try:
        empresa = _empresa_por_nif_o_falla(conn, nif)
        if empresa is None:
            return
        try:
            guardar_credenciales_smtp(conn, empresa["id"], host, puerto, usuario, password)
        except ValueError as exc:
            print(f"Error: {exc}")
            return
        print(f"Credenciales SMTP guardadas correctamente para {empresa['nombre']} ({usuario} vía {host}:{puerto}).")
    finally:
        conn.close()


def listar(nif: str) -> None:
    conn = get_connection()
    try:
        empresa = _empresa_por_nif_o_falla(conn, nif)
        if empresa is None:
            return
        fila = obtener_credenciales_smtp(conn, empresa["id"])
        if fila is None:
            print(f"{empresa['nombre']} no tiene credenciales SMTP configuradas todavía.")
            return
        datos = descifrar_credenciales_smtp(fila)
        estado = "" if fila["activa"] else " (inactiva)"
        print(f"{empresa['nombre']}: {datos['usuario']} vía {datos['host']}:{datos['puerto']}{estado} (contraseña oculta)")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gestiona las credenciales SMTP de envío de una empresa.")
    subparsers = parser.add_subparsers(dest="accion", required=True)

    p_alta = subparsers.add_parser("alta")
    p_alta.add_argument("nif")
    p_alta.add_argument("host")
    p_alta.add_argument("puerto", type=int)
    p_alta.add_argument("usuario")

    p_listar = subparsers.add_parser("listar")
    p_listar.add_argument("nif")

    args = parser.parse_args(argv)

    if args.accion == "alta":
        # La contraseña de aplicación se pide de forma interactiva (sin eco en
        # pantalla, como con `sudo`) para que nunca quede en el historial del shell
        # ni visible en la terminal.
        password = getpass.getpass("Contraseña de aplicación (no se mostrará en pantalla): ")
        alta(args.nif, args.host, args.puerto, args.usuario, password)
    elif args.accion == "listar":
        listar(args.nif)


if __name__ == "__main__":
    main()
