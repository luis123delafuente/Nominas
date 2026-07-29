"""Cifrado en reposo de campos sensibles individuales (IBAN, BIC, y cualquier otro que
se añada más adelante) antes de guardarlos en SQLite.

Decisión de arquitectura: cifrado a nivel de campo con `cryptography.fernet.Fernet`
(AES-128-CBC + HMAC-SHA256 autenticado), en vez de cifrar la base de datos entera con
SQLCipher. Motivos, para un sistema que corre en un único Mac por cliente:

- SQLCipher exige sustituir el módulo `sqlite3` de la librería estándar por un binario
  nativo (`pysqlcipher3` o equivalente) que hay que compilar o empaquetar por Mac y por
  versión de Python. Eso complica el arranque de doble clic (`Iniciar_App.command`) y
  el requisito de "cero dependencias de pago/nube" no prohíbe esto, pero sí lo hace
  frágil de instalar en el Mac de un cliente no técnico.
- `cryptography` ya es una dependencia del proyecto (requirements.txt, usada de forma
  indirecta por `pypdf`), así que no añade nada nuevo al arranque.
- El cifrado a nivel de campo permite seguir consultando y depurando el resto de la
  base de datos (nombres, emails, estado de envíos) en texto plano con cualquier
  herramienta de SQLite, mientras que solo IBAN/BIC quedan protegidos — que es
  exactamente el dato sensible nuevo que se va a añadir. Cifrar toda la base sería
  además cifrar de nuevo el DNI, que ya se decidió mantener en texto plano (Fase 8.4 /
  fichero maestro: se usa tal cual como contraseña de los PDF).
- Fernet añade autenticación (HMAC): si alguien manipula el valor cifrado en la base de
  datos a mano, `descifrar_campo` lo detecta y lanza un error en vez de devolver datos
  corruptos en silencio.

La clave vive en `data/clave_cifrado.key`, generada automáticamente la primera vez que
se cifra algo, y NUNCA se sube a git (ver .gitignore) — igual que `config.local.py`.
Si se pierde esa clave, los campos cifrados ya guardados son irrecuperables: no hay
"clave de recuperación" alternativa, es una decisión consciente de simplicidad para un
sistema de un solo Mac (no hay servidor central donde depositar una copia).
"""

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = Path(__file__).resolve().parent.parent
RUTA_CLAVE_POR_DEFECTO = BASE_DIR / "data" / "clave_cifrado.key"


class CifradoError(Exception):
    """El valor cifrado no se puede descifrar: clave equivocada o dato manipulado/corrupto."""


def _cargar_o_generar_clave(ruta: Path) -> bytes:
    if ruta.exists():
        return ruta.read_bytes()

    ruta.parent.mkdir(parents=True, exist_ok=True)
    clave = Fernet.generate_key()
    ruta.write_bytes(clave)
    ruta.chmod(0o600)  # solo el propietario puede leerla
    return clave


def _fernet(ruta_clave: Path) -> Fernet:
    return Fernet(_cargar_o_generar_clave(ruta_clave))


def cifrar_campo(texto_claro: str | None, ruta_clave: Path = RUTA_CLAVE_POR_DEFECTO) -> str | None:
    """Cifra un valor sensible (IBAN, BIC...) antes de guardarlo en una columna TEXT.

    `None` pasa intacto, para que los llamadores puedan tratar columnas opcionales sin
    tener que comprobar antes si hay valor.
    """
    if texto_claro is None:
        return None
    token = _fernet(ruta_clave).encrypt(texto_claro.encode("utf-8"))
    return token.decode("ascii")


def descifrar_campo(texto_cifrado: str | None, ruta_clave: Path = RUTA_CLAVE_POR_DEFECTO) -> str | None:
    """Inverso de `cifrar_campo`. Lanza `CifradoError` si la clave no coincide o el
    valor ha sido manipulado — nunca devuelve un dato a medio descifrar."""
    if texto_cifrado is None:
        return None
    try:
        token = _fernet(ruta_clave).decrypt(texto_cifrado.encode("ascii"))
    except InvalidToken as exc:
        raise CifradoError(
            "No se ha podido descifrar el valor: la clave no coincide o el dato está corrupto."
        ) from exc
    return token.decode("utf-8")
