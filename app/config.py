import importlib.util
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUTA_CONFIG_LOCAL = BASE_DIR / "config.local.py"

MODOS_ENVIO_VALIDOS = {"prueba", "produccion"}
MODO_ENVIO_POR_DEFECTO = "prueba"  # seguro por defecto: nunca "produccion" si algo falta


@dataclass
class Configuracion:
    modo_envio: str
    email_prueba: str | None


def cargar_configuracion(ruta: Path = RUTA_CONFIG_LOCAL) -> Configuracion:
    """Carga config.local.py si existe. Si no existe, o su MODO_ENVIO no es válido,
    cae de forma segura a modo "prueba" — nunca a "produccion" por omisión.
    """
    if not ruta.exists():
        return Configuracion(modo_envio=MODO_ENVIO_POR_DEFECTO, email_prueba=None)

    spec = importlib.util.spec_from_file_location("config_local", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    modo_envio = getattr(modulo, "MODO_ENVIO", MODO_ENVIO_POR_DEFECTO)
    if modo_envio not in MODOS_ENVIO_VALIDOS:
        modo_envio = MODO_ENVIO_POR_DEFECTO

    email_prueba = getattr(modulo, "EMAIL_PRUEBA", None)

    return Configuracion(modo_envio=modo_envio, email_prueba=email_prueba)
