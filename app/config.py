import importlib.util
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUTA_CONFIG_LOCAL = BASE_DIR / "config.local.py"

MODOS_ENVIO_VALIDOS = {"prueba", "produccion"}
MODO_ENVIO_POR_DEFECTO = "prueba"  # seguro por defecto: nunca "produccion" si algo falta


class GeneracionBloqueadaPorModoPrueba(Exception):
    """Se ha intentado generar un fichero real (SEPA, email, o cualquier futuro fichero
    subible a un sistema externo) estando en modo prueba."""


@dataclass
class Configuracion:
    modo_envio: str
    email_prueba: str | None


def cargar_configuracion(ruta: Path | None = None) -> Configuracion:
    """Carga config.local.py si existe. Si no existe, o su MODO_ENVIO no es válido,
    cae de forma segura a modo "prueba" — nunca a "produccion" por omisión.
    """
    if ruta is None:
        ruta = RUTA_CONFIG_LOCAL  # búsqueda dinámica (no como valor por defecto del parámetro):
        # así los tests pueden aislarse del config.local.py real con monkeypatch.setattr
        # sobre este nombre de módulo, en vez de heredar sin querer el modo de envío real.
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


def asegurar_generacion_permitida(config: Configuracion, descripcion: str) -> None:
    """Bloquea la generación de cualquier fichero real (fichero SEPA subible al banco,
    y en el futuro cualquier otro fichero con el mismo riesgo) mientras MODO_ENVIO no
    sea "produccion".

    El envío de email ya tiene su propio mecanismo de redirección en
    `mailer_smtp.resolver_destinatario` (nunca sale un correo real en modo prueba,
    aunque sí se genera el PDF cifrado). Esta función cubre el resto de ficheros que
    vayan a subirse a un sistema externo (banco u otro), donde no basta con redirigir
    el destinatario: en modo prueba no debe llegar a existir el fichero.

    Debe llamarse ANTES de escribir el fichero, no después — el generador SEPA (Fase 2
    de ROADMAP_NOMINAS.md) tendrá que llamar a esto como primera línea.
    """
    if config.modo_envio != "produccion":
        raise GeneracionBloqueadaPorModoPrueba(
            f"No se puede generar '{descripcion}': MODO_ENVIO es '{config.modo_envio}'. "
            "Cambia a 'produccion' en config.local.py para generar ficheros reales."
        )
