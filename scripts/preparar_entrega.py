"""Script de un solo uso: empaqueta el proyecto en un .zip listo para entregar.

Copia el proyecto completo a una carpeta temporal (fuera del repositorio),
excluyendo el entorno de desarrollo y los datos sensibles/temporales, pero
conservando data/nominas.db tal cual (con el historial real de envíos). No
toca nada del proyecto real: todo opera sobre la copia temporal.

Uso:
    ./venv/bin/python3 scripts/preparar_entrega.py
"""

import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
NOMBRE_CARPETA_ENTREGA = "nominas-mediformplus"

# Carpetas que no deben copiarse en absoluto (entorno de desarrollo, cachés, control de versiones).
EXCLUIR_DIRS = {"venv", "__pycache__", ".pytest_cache", ".git"}

# Archivos sueltos que no deben copiarse (config.local.py es el real, con datos de este ordenador;
# config.local.example.py sí se conserva, es la plantilla).
EXCLUIR_ARCHIVOS = {"config.local.py", ".DS_Store"}

# Carpetas cuyo CONTENIDO no debe copiarse (son datos de trabajo, no parte del proyecto en sí),
# pero que deben llegar vacías con su .gitkeep para que la app las encuentre ya creadas.
CARPETAS_A_VACIAR = {"entrada", "salida"}


def construir_ignorador(excluidos: list):
    """Devuelve la función `ignore` que usa shutil.copytree, registrando en `excluidos`
    cada carpeta/archivo que se salta, para poder imprimir el resumen al final."""

    def ignorador(directorio: str, nombres: list) -> set:
        rel_dir = Path(directorio).relative_to(RAIZ_PROYECTO)
        a_ignorar = set()

        for nombre in nombres:
            ruta_rel = str(rel_dir / nombre) if str(rel_dir) != "." else nombre

            if nombre in EXCLUIR_DIRS or nombre in EXCLUIR_ARCHIVOS:
                a_ignorar.add(nombre)
                excluidos.append(ruta_rel)
            elif str(rel_dir) in CARPETAS_A_VACIAR and nombre != ".gitkeep":
                a_ignorar.add(nombre)
                excluidos.append(ruta_rel)
            elif str(rel_dir) == "data" and nombre not in {"nominas.db", ".gitkeep"}:
                # Cualquier otra cosa en data/ (p.ej. copias de seguridad de migraciones)
                # no forma parte de la entrega: solo se conserva la base de datos real.
                a_ignorar.add(nombre)
                excluidos.append(ruta_rel)

        return a_ignorar

    return ignorador


def main() -> None:
    fecha = date.today().strftime("%Y%m%d")
    ruta_zip_final = RAIZ_PROYECTO.parent / f"entrega_nominas_{fecha}.zip"

    tmp_dir = Path(tempfile.mkdtemp(prefix="entrega_nominas_"))
    carpeta_copia = tmp_dir / NOMBRE_CARPETA_ENTREGA

    excluidos: list = []
    tamano_db_kb = 0.0
    try:
        shutil.copytree(RAIZ_PROYECTO, carpeta_copia, ignore=construir_ignorador(excluidos))

        ruta_db_copia = carpeta_copia / "data" / "nominas.db"
        if not ruta_db_copia.exists():
            print("ERROR: data/nominas.db no existe en el proyecto real; abortando.", file=sys.stderr)
            sys.exit(1)
        tamano_db_kb = ruta_db_copia.stat().st_size / 1024

        ruta_zip_sin_extension = ruta_zip_final.with_suffix("")
        shutil.make_archive(str(ruta_zip_sin_extension), "zip", root_dir=tmp_dir, base_dir=NOMBRE_CARPETA_ENTREGA)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    tamano_zip_mb = ruta_zip_final.stat().st_size / (1024 * 1024)

    print("=== Entrega preparada ===")
    print(f"Zip generado: {ruta_zip_final} ({tamano_zip_mb:.1f} MB)")
    print()
    print("Incluido:")
    print("  - Proyecto completo (app/, tests/, templates, scripts, MANUAL_USO.md, etc.)")
    print(f"  - data/nominas.db tal cual ({tamano_db_kb:.0f} KB), con el historial real de envíos")
    print("  - config.local.example.py (plantilla, sin datos reales)")
    print("  - entrada/ y salida/ presentes pero vacías (solo su .gitkeep)")
    print()
    print(f"Excluido ({len(excluidos)} elementos):")
    for ruta in sorted(excluidos):
        print(f"  - {ruta}")


if __name__ == "__main__":
    main()
