"""Actualiza el código de una instalación YA EXISTENTE (con datos reales de un cliente)
a partir de una copia más reciente del proyecto, sin tocar nunca sus datos.

A diferencia de preparar_entrega.py (que empaqueta una entrega nueva, incluyendo
data/nominas.db de desarrollo como base inicial), este script asume que el DESTINO
ya tiene su propia base de datos, su propia clave de cifrado y sus propias
credenciales SMTP/bancarias, y que perder cualquiera de esas cosas sería grave.

Solo reemplaza lo que es 100% código (nunca datos de un cliente concreto):
    app/, scripts/, schemas/, tests/, requirements.txt, Iniciar_App.command,
    los .md de la raíz, config.local.example.py

Nunca toca (ni siquiera para leer):
    data/, entrada/, salida/, logs/, config.local.py, venv/

Por defecto corre en modo simulación (dry-run): solo imprime qué haría.
Hay que pasar --aplicar para que escriba de verdad.

Si un archivo suelto (p.ej. Iniciar_App.command) fue modificado a mano en el
DESTINO respecto a la versión que tenías en origen la última vez —típicamente
porque el cliente necesitó un ajuste propio en esa máquina—, el script NO lo
sobrescribe por defecto: lo omite y avisa, para no perder ese ajuste sin
darte cuenta. Hace falta --forzar para sobrescribirlo también.

Uso:
    ./venv/bin/python3 scripts/aplicar_actualizacion.py ORIGEN DESTINO [--aplicar] [--forzar]

    ORIGEN  = carpeta con el código nuevo (p.ej. este repo ya actualizado con
              `git pull`, o una copia recién traída al Mac del cliente).
    DESTINO = carpeta de la instalación real del cliente
              (p.ej. ~/Aplicaciones-Locales/nominas-mediformplus/).
"""

import filecmp
import shutil
import sys
from datetime import datetime
from pathlib import Path

CARPETAS_CODIGO = ["app", "scripts", "schemas", "tests"]
ARCHIVOS_CODIGO_SUELTOS_FIJOS = [
    "requirements.txt",
    "Iniciar_App.command",
    "config.local.example.py",
]

# Rutas que jamás se tocan, pase lo que pase (datos reales del cliente).
INTOCABLE = {"data", "entrada", "salida", "logs", "config.local.py", "venv"}


def listar_markdown(origen: Path) -> list:
    return sorted(p.name for p in origen.glob("*.md"))


def comprobar_destino_es_instalacion_real(destino: Path) -> None:
    """Aborta si `destino` no parece una instalación ya configurada, para evitar
    ejecutar esto por error contra la carpeta equivocada (o una carpeta vacía)."""
    db = destino / "data" / "nominas.db"
    config = destino / "config.local.py"
    faltantes = [str(p) for p in (db, config) if not p.exists()]
    if faltantes:
        print("ERROR: el destino no parece una instalación real y configurada.", file=sys.stderr)
        print("No se encontró:", file=sys.stderr)
        for f in faltantes:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nSi es una instalación nueva sin datos todavía, usa preparar_entrega.py, "
            "no este script.",
            file=sys.stderr,
        )
        sys.exit(1)


def hacer_backup(destino: Path, archivos_sueltos: list) -> Path:
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = destino.parent / f"{destino.name}_backup_codigo_{marca}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for nombre in CARPETAS_CODIGO:
        origen_carpeta = destino / nombre
        if origen_carpeta.exists():
            shutil.copytree(origen_carpeta, backup_dir / nombre)
    for nombre in archivos_sueltos:
        archivo_destino = destino / nombre
        if archivo_destino.exists():
            shutil.copy2(archivo_destino, backup_dir / nombre)
    return backup_dir


def difiere_del_origen(origen_archivo: Path, destino_archivo: Path) -> bool:
    """True si el destino tiene ese archivo y su contenido no coincide con el de
    origen — indicio de que alguien lo modificó a mano en esa máquina en concreto."""
    if not destino_archivo.exists():
        return False
    return not filecmp.cmp(origen_archivo, destino_archivo, shallow=False)


def main() -> None:
    argumentos = [a for a in sys.argv[1:] if a not in ("--aplicar", "--forzar")]
    aplicar = "--aplicar" in sys.argv
    forzar = "--forzar" in sys.argv

    if len(argumentos) != 2:
        print(__doc__)
        sys.exit(1)

    origen = Path(argumentos[0]).expanduser().resolve()
    destino = Path(argumentos[1]).expanduser().resolve()

    if not origen.exists():
        print(f"ERROR: el origen no existe: {origen}", file=sys.stderr)
        sys.exit(1)

    comprobar_destino_es_instalacion_real(destino)

    if origen == destino:
        print("ERROR: origen y destino son la misma carpeta.", file=sys.stderr)
        sys.exit(1)

    archivos_sueltos = list(ARCHIVOS_CODIGO_SUELTOS_FIJOS) + listar_markdown(origen)

    print(f"Origen:  {origen}")
    print(f"Destino: {destino}")
    print(f"Modo:    {'APLICANDO CAMBIOS' if aplicar else 'simulación (dry-run)'}")
    print()
    print("Se reemplazará por completo (borrar + copiar de nuevo):")
    for nombre in CARPETAS_CODIGO:
        existe = "sí" if (origen / nombre).exists() else "NO EXISTE EN ORIGEN"
        print(f"  - {nombre}/  ({existe})")
    modificados_en_destino = {
        nombre
        for nombre in archivos_sueltos
        if (origen / nombre).exists() and difiere_del_origen(origen / nombre, destino / nombre)
    }

    print()
    print("Se sobrescribirá (archivo suelto):")
    for nombre in archivos_sueltos:
        if not (origen / nombre).exists():
            print(f"  - {nombre}  (NO EXISTE EN ORIGEN, se omite)")
        elif nombre in modificados_en_destino:
            if forzar:
                print(f"  - {nombre}  (MODIFICADO EN EL DESTINO — se sobrescribe igualmente por --forzar)")
            else:
                print(f"  - {nombre}  (MODIFICADO EN EL DESTINO — se OMITE, usa --forzar si quieres pisarlo)")
        else:
            print(f"  - {nombre}  (sí)")
    print()
    print("Nunca se toca:", ", ".join(sorted(INTOCABLE)))

    if modificados_en_destino and not forzar:
        print(
            "\nAVISO: hay archivos sueltos que en el destino no coinciden con el origen "
            "(probablemente ajustes propios de esa máquina). No se van a tocar salvo que "
            "repitas con --forzar. Revísalos a mano si crees que el ajuste debería incorporarse "
            "al repositorio para que no se pierda en la próxima actualización."
        )

    if not aplicar:
        print("\nSimulación únicamente. Repite con --aplicar para ejecutar de verdad.")
        return

    print()
    backup_dir = hacer_backup(destino, archivos_sueltos)
    print(f"Backup del código anterior guardado en: {backup_dir}")

    for nombre in CARPETAS_CODIGO:
        origen_carpeta = origen / nombre
        if not origen_carpeta.exists():
            continue
        destino_carpeta = destino / nombre
        if destino_carpeta.exists():
            shutil.rmtree(destino_carpeta)
        shutil.copytree(origen_carpeta, destino_carpeta)
        print(f"  {nombre}/ actualizado")

    for nombre in archivos_sueltos:
        origen_archivo = origen / nombre
        if not origen_archivo.exists():
            continue
        if nombre in modificados_en_destino and not forzar:
            print(f"  {nombre} OMITIDO (modificado en destino, usa --forzar para pisarlo)")
            continue
        shutil.copy2(origen_archivo, destino / nombre)
        print(f"  {nombre} actualizado")

    print()
    print("=== Código actualizado. Datos del cliente no tocados. ===")
    print("Próximos pasos manuales en el Mac del cliente:")
    print(f"  cd {destino}")
    print("  ./venv/bin/pip install -r requirements.txt")
    print("  ./Iniciar_App.command   (las migraciones de la BD se aplican solas al arrancar)")


if __name__ == "__main__":
    main()
