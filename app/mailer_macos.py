import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import Configuracion, cargar_configuracion
from app.db import obtener_empresa, registrar_envio

TIMEOUT_OSASCRIPT_SEGUNDOS = 30


class ConfiguracionInvalida(Exception):
    """El modo de envío requiere un dato de configuración que falta."""


class EnvioError(Exception):
    """El envío de un correo concreto ha fallado (Mail.app, AppleScript, adjunto, etc.)."""


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


def _escapar_applescript(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"')


def _construir_script_envio(email_destino: str, asunto: str, cuerpo: str, ruta_adjunto: str) -> str:
    """Construye el AppleScript que compone y envía el correo desde Mail.app.

    `tell application "Mail"` abre Mail.app automáticamente si estaba cerrada,
    no hace falta comprobar si ya está en marcha.
    """
    email_esc = _escapar_applescript(email_destino)
    asunto_esc = _escapar_applescript(asunto)
    cuerpo_esc = _escapar_applescript(cuerpo)
    ruta_esc = _escapar_applescript(ruta_adjunto)

    return f'''
tell application "Mail"
    set nuevoMensaje to make new outgoing message with properties {{subject:"{asunto_esc}", content:"{cuerpo_esc}", visible:false}}
    tell nuevoMensaje
        make new to recipient at end of to recipients with properties {{address:"{email_esc}"}}
        make new attachment with properties {{file name:(POSIX file "{ruta_esc}" as alias)}} at after last paragraph of content
    end tell
    send nuevoMensaje
end tell
'''


def _ejecutar_applescript(script: str, timeout: int = TIMEOUT_OSASCRIPT_SEGUNDOS) -> None:
    resultado = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if resultado.returncode != 0:
        raise EnvioError(resultado.stderr.strip() or "osascript devolvió un error sin detalle")


@dataclass
class ResultadoEnvio:
    empleado_id: int
    estado: str  # "enviado" / "error"
    email_destino: str
    email_produccion: str | None
    detalle: str | None


def enviar_nomina(
    conn: sqlite3.Connection,
    empleado_id: int,
    empresa_id: int,
    nombre_empleado: str,
    email_empleado: str,
    mes_nomina: str,
    ruta_pdf_cifrado: str,
    config: Configuracion | None = None,
) -> ResultadoEnvio:
    """Compone y envía por Mail.app la nómina cifrada de un empleado, y registra el resultado en envios_log.

    Cualquier fallo (Mail.app, AppleScript, adjunto inexistente, config inválida) se
    captura aquí a propósito: esta función se llama en lote sobre ~25 nóminas y un
    fallo individual no debe abortar el resto del envío.
    """
    if config is None:
        config = cargar_configuracion()

    fecha_hora = datetime.now().isoformat(timespec="seconds")
    destinatario: DestinatarioResuelto | None = None

    try:
        destinatario = resolver_destinatario(email_empleado, config)

        ruta_adjunto = Path(ruta_pdf_cifrado)
        if not ruta_adjunto.exists():
            raise EnvioError(f"El PDF cifrado no existe en la ruta esperada: {ruta_pdf_cifrado}")

        empresa = obtener_empresa(conn, empresa_id)
        if empresa is None:
            raise EnvioError(f"No existe ninguna empresa con id={empresa_id}")
        nombre_empresa = empresa["nombre"]

        nota = nota_modo_prueba(destinatario)

        asunto = f"Nómina {nombre_empresa} - {mes_nomina}"
        if nota:
            asunto = f"{nota} — {asunto}"

        cuerpo = (
            f"Hola {nombre_empleado},\n\n"
            f"Adjuntamos tu nómina de {nombre_empresa} correspondiente a {mes_nomina}.\n\n"
            "Un saludo."
        )
        if nota:
            cuerpo = f"{nota}\n\n{cuerpo}"

        script = _construir_script_envio(destinatario.email_envio, asunto, cuerpo, str(ruta_adjunto.resolve()))
        _ejecutar_applescript(script)

    except Exception as exc:
        detalle = str(exc) or type(exc).__name__
        email_destino = destinatario.email_envio if destinatario else ""
        email_produccion = destinatario.email_produccion if destinatario else None
        try:
            registrar_envio(
                conn,
                fecha_hora,
                mes_nomina,
                empleado_id,
                empresa_id,
                email_destino,
                estado="error",
                detalle=detalle,
                email_produccion=email_produccion,
            )
        except Exception:
            # Si ni siquiera se puede registrar el error (p.ej. empresa_id o empleado_id
            # inválidos, que violan la FK de envios_log), no dejamos que esto aborte el
            # resto del lote: se pierde ese registro en el histórico, pero no el resto de envíos.
            pass
        return ResultadoEnvio(empleado_id, "error", email_destino, email_produccion, detalle)

    registrar_envio(
        conn,
        fecha_hora,
        mes_nomina,
        empleado_id,
        empresa_id,
        destinatario.email_envio,
        estado="enviado",
        email_produccion=destinatario.email_produccion,
    )
    return ResultadoEnvio(empleado_id, "enviado", destinatario.email_envio, destinatario.email_produccion, None)


@dataclass
class NominaParaEnviar:
    empleado_id: int
    empresa_id: int
    nombre_empleado: str
    email_empleado: str
    mes_nomina: str
    ruta_pdf_cifrado: str


@dataclass
class ResumenLoteEnvio:
    resultados: list[ResultadoEnvio]

    @property
    def enviados(self) -> int:
        return sum(1 for r in self.resultados if r.estado == "enviado")

    @property
    def errores(self) -> int:
        return sum(1 for r in self.resultados if r.estado == "error")


def enviar_lote(
    conn: sqlite3.Connection,
    nominas: list[NominaParaEnviar],
    config: Configuracion | None = None,
) -> ResumenLoteEnvio:
    """Envía cada nómina de la lista, continuando aunque alguna falle, y devuelve el resumen del lote."""
    if config is None:
        config = cargar_configuracion()

    resultados = [
        enviar_nomina(
            conn,
            nomina.empleado_id,
            nomina.empresa_id,
            nomina.nombre_empleado,
            nomina.email_empleado,
            nomina.mes_nomina,
            nomina.ruta_pdf_cifrado,
            config,
        )
        for nomina in nominas
    ]
    return ResumenLoteEnvio(resultados=resultados)
