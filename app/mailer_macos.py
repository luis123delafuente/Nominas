from dataclasses import dataclass

from app.config import Configuracion


class ConfiguracionInvalida(Exception):
    """El modo de envío requiere un dato de configuración que falta."""


@dataclass
class DestinatarioResuelto:
    email_envio: str  # a quién se envía el correo de verdad
    email_produccion: str | None  # a quién habría ido en producción (solo relevante en modo prueba)
    es_modo_prueba: bool


def resolver_destinatario(email_empleado: str, config: Configuracion) -> DestinatarioResuelto:
    """Decide el destinatario real de un envío según el modo de envío configurado.

    En modo "prueba", el destinatario es SIEMPRE EMAIL_PRUEBA, sin excepción,
    para que un email real no pueda salir por accidente durante el desarrollo.
    """
    if config.modo_envio == "prueba":
        if not config.email_prueba:
            raise ConfiguracionInvalida(
                "MODO_ENVIO es 'prueba' pero no hay EMAIL_PRUEBA configurado en config.local.py"
            )
        return DestinatarioResuelto(
            email_envio=config.email_prueba,
            email_produccion=email_empleado,
            es_modo_prueba=True,
        )

    return DestinatarioResuelto(email_envio=email_empleado, email_produccion=None, es_modo_prueba=False)


def nota_modo_prueba(destinatario: DestinatarioResuelto) -> str | None:
    """Texto bien visible para asunto/cuerpo del correo cuando se está redirigiendo por modo prueba."""
    if not destinatario.es_modo_prueba:
        return None
    return f"[PRUEBA] destinatario real: {destinatario.email_produccion}"
