"""Envío de nóminas por email vía SMTP — sustituye a `mailer_macos.py` (Mail.app/
AppleScript, exclusivo de macOS). Usa la cuenta de email propia de cada empresa
(credenciales en `credenciales_smtp`, ver app/db.py), nunca un servicio transaccional
de terceros, y funciona igual en Mac, Windows y Linux: solo depende de `smtplib` de la
librería estándar de Python.

Mantiene el mismo comportamiento de modo prueba que ya existía para Mail.app: en modo
"prueba" el destinatario se redirige a EMAIL_PRUEBA en vez de bloquear el envío (a
diferencia de `asegurar_generacion_permitida()`, usado para el fichero SEPA) — la
nómina cifrada se sigue generando y enviando de verdad, solo que a una dirección de
prueba, para poder validar visualmente el resultado sin arriesgar un envío real.
"""

import smtplib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from app.config import Configuracion, cargar_configuracion
from app.db import descifrar_credenciales_smtp, obtener_credenciales_smtp, obtener_empresa, registrar_envio

PUERTO_SSL_IMPLICITO = 465
TIMEOUT_SMTP_SEGUNDOS = 30


class ConfiguracionInvalida(Exception):
    """El modo de envío, o las credenciales SMTP de la empresa, requieren un dato que falta."""


class EnvioError(Exception):
    """El envío de un correo concreto ha fallado (conexión SMTP, autenticación, adjunto, etc.)."""


@dataclass
class DestinatarioResuelto:
    email_envio: str  # a quién se envía el correo de verdad
    email_produccion: str | None  # a quién habría ido en producción (solo relevante en modo prueba)
    es_modo_prueba: bool


def resolver_destinatario(email_empleado: str, config: Configuracion) -> DestinatarioResuelto:
    """Decide el destinatario real de un envío según el modo de envío configurado.

    En modo "prueba", el destinatario es SIEMPRE EMAIL_PRUEBA, sin excepción, para que
    un email real no pueda salir por accidente durante el desarrollo. Idéntico
    comportamiento al que ya existía en mailer_macos.py.
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


def _construir_mensaje(remitente: str, email_destino: str, asunto: str, cuerpo: str, ruta_adjunto: Path) -> EmailMessage:
    mensaje = EmailMessage()
    mensaje["From"] = remitente
    mensaje["To"] = email_destino
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    mensaje.add_attachment(
        ruta_adjunto.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=ruta_adjunto.name,
    )
    return mensaje


def _enviar_via_smtp(host: str, puerto: int, usuario: str, password: str, mensaje: EmailMessage) -> None:
    """Conecta y envía. Puerto 465 -> TLS implícito (SMTP_SSL); cualquier otro puerto
    (587 típicamente) -> conexión en claro seguida de STARTTLS, que es lo que piden
    tanto Gmail como Outlook/Office365. No hay lógica específica de un proveedor."""
    try:
        if puerto == PUERTO_SSL_IMPLICITO:
            with smtplib.SMTP_SSL(host, puerto, timeout=TIMEOUT_SMTP_SEGUNDOS) as servidor:
                servidor.login(usuario, password)
                servidor.send_message(mensaje)
        else:
            with smtplib.SMTP(host, puerto, timeout=TIMEOUT_SMTP_SEGUNDOS) as servidor:
                servidor.starttls()
                servidor.login(usuario, password)
                servidor.send_message(mensaje)
    except (smtplib.SMTPException, OSError) as exc:
        raise EnvioError(str(exc) or type(exc).__name__) from exc


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
    ruta_clave: Path | None = None,
) -> ResultadoEnvio:
    """Compone y envía por SMTP la nómina cifrada de un empleado, con las credenciales
    propias de `empresa_id`, y registra el resultado en envios_log.

    Cualquier fallo (config inválida, credenciales SMTP ausentes, adjunto inexistente,
    error del servidor SMTP) se captura aquí a propósito: esta función se llama en lote
    sobre ~25 nóminas y un fallo individual no debe abortar el resto del envío.
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

        credenciales_fila = obtener_credenciales_smtp(conn, empresa_id)
        if credenciales_fila is None or not credenciales_fila["activa"]:
            raise ConfiguracionInvalida(
                f"No hay credenciales SMTP activas configuradas para '{nombre_empresa}'. "
                "Dalas de alta con scripts/gestionar_smtp_empresa.py."
            )
        credenciales = descifrar_credenciales_smtp(credenciales_fila, ruta_clave=ruta_clave)

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

        mensaje = _construir_mensaje(credenciales["usuario"], destinatario.email_envio, asunto, cuerpo, ruta_adjunto)
        _enviar_via_smtp(
            credenciales["host"], credenciales["puerto"], credenciales["usuario"], credenciales["password"], mensaje
        )

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
    ruta_clave: Path | None = None,
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
            ruta_clave,
        )
        for nomina in nominas
    ]
    return ResumenLoteEnvio(resultados=resultados)
