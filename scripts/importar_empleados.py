"""Script de un solo uso: importa empleados desde un Excel a data/nominas.db.

Uso:
    ./venv/bin/python3 scripts/importar_empleados.py ruta/al/excel.xlsx

Formato esperado del Excel (hoja única):
    - Cabecera en la fila 8.
    - Datos desde la fila 10, columnas C=TRABAJADOR (APELLIDOS, NOMBRE),
      D=DNI, E=mail. Se ignoran B (código) y F (cuenta empresa).
    - Termina en la primera fila donde C, D y E estén todas vacías.

fecha_alta se registra como la fecha de ejecución del script (hoy).
No falla el proceso completo por una fila mala: la lista como "omitida"
y sigue con el resto. Puede ejecutarse varias veces sin duplicar nada,
porque un DNI ya existente en la base de datos se omite.
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

from app.db import crear_empleado, get_connection
from app.pdf_parser import DNI_NIE_PATTERN

FILA_CABECERA = 8
FILA_PRIMER_DATO = 10
COL_NOMBRE = "C"
COL_DNI = "D"
COL_EMAIL = "E"


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def _normalizar_dni(valor) -> str:
    return _texto(valor).upper().replace(" ", "")


def importar(ruta_excel: str) -> None:
    wb = openpyxl.load_workbook(ruta_excel, data_only=True)
    hoja = wb.active

    conn = get_connection()

    importados: list[tuple[int, str, str]] = []
    omitidos: list[tuple[int, str]] = []

    fila_num = FILA_PRIMER_DATO
    while True:
        nombre = _texto(hoja[f"{COL_NOMBRE}{fila_num}"].value)
        dni_crudo = hoja[f"{COL_DNI}{fila_num}"].value
        email = _texto(hoja[f"{COL_EMAIL}{fila_num}"].value)

        if not nombre and not dni_crudo and not email:
            break  # primera fila totalmente vacía -> fin de los datos

        dni = _normalizar_dni(dni_crudo)

        if not nombre:
            omitidos.append((fila_num, "falta el nombre (columna C)"))
        elif not email:
            omitidos.append((fila_num, "falta el email (columna E)"))
        elif not dni:
            omitidos.append((fila_num, "falta el DNI/NIE (columna D)"))
        elif not DNI_NIE_PATTERN.match(dni):
            omitidos.append((fila_num, f"DNI/NIE con formato inválido: '{dni_crudo}'"))
        else:
            try:
                crear_empleado(conn, nombre, dni, email, date.today().isoformat())
                importados.append((fila_num, nombre, dni))
            except sqlite3.IntegrityError:
                omitidos.append((fila_num, f"el DNI {dni} ya existe en la base de datos (empleado no importado de nuevo)"))

        fila_num += 1

    conn.close()

    print(f"Importados correctamente: {len(importados)}")
    for fila_num, nombre, dni in importados:
        print(f"  fila {fila_num}: {nombre} ({dni})")

    print(f"\nOmitidos: {len(omitidos)}")
    for fila_num, motivo in omitidos:
        print(f"  fila {fila_num}: {motivo}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: ./venv/bin/python3 scripts/importar_empleados.py ruta/al/excel.xlsx")
        sys.exit(1)

    importar(sys.argv[1])
