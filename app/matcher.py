import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

# Umbral del fallback fuzzy por nombre (solo se usa si la nómina no trae un DNI/NIE
# extraíble). Conservador a propósito: mejor marcar "sin match" y revisar a mano
# que enviarle a alguien la nómina (salario, DNI, IBAN) de otro compañero.
UMBRAL_MATCH_AUTOMATICO = 90

# Si el DNI coincide exactamente pero el nombre se parece menos que esto al de
# la ficha del empleado, no se acepta en silencio: puede ser un error de tecleo
# en la BD o un DNI mal extraído del PDF, y hay que verlo en la revisión manual.
UMBRAL_ALERTA_NOMBRE = 50


def _normalizar_nombre(nombre: str) -> str:
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c))
    return " ".join(sin_acentos.replace(",", " ").upper().split())


def _normalizar_dni(dni: str) -> str:
    return dni.strip().upper().replace(" ", "")


def _mejor_candidato_por_nombre(nombre_normalizado: str, empleados):
    mejor_empleado = None
    mejor_score = 0.0
    for empleado in empleados:
        score = fuzz.token_sort_ratio(nombre_normalizado, _normalizar_nombre(empleado["nombre_completo"]))
        if score > mejor_score:
            mejor_score = score
            mejor_empleado = empleado
    return mejor_empleado, mejor_score


@dataclass
class ResultadoMatch:
    empleado: object | None  # fila del empleado emparejado (o candidato sugerido), o None
    metodo: str  # "dni_exacto" / "dni_con_alerta_nombre" / "dni_dudoso_nombre_coincide" / "fuzzy_nombre" / "sin_match"
    score_nombre: float  # similitud de nombre, siempre informado aunque el match sea por DNI


def emparejar_nomina(
    nombre_pdf: str,
    dni_pdf: str | None,
    empleados,
    umbral_fuzzy: float = UMBRAL_MATCH_AUTOMATICO,
) -> ResultadoMatch:
    """Empareja una nómina (nombre + DNI extraídos del PDF) contra los `empleados` de la BD.

    Prioridad:
      1. DNI exacto -> es esa persona, sin ambigüedad (con alerta si el nombre no cuadra).
      2. Si la nómina no traía un DNI con formato reconocible, fallback a fuzzy por nombre.
      3. Si trae un DNI con formato válido que no está en la BD, puede ser un DNI mal
         leído del PDF (p.ej. el OCR cambia la letra de control, 54413522F -> 54413522E):
         si el nombre coincide fuerte con una ficha, se sugiere esa ficha con alerta
         (`dni_dudoso_nombre_coincide`) para confirmación manual. Sin esa coincidencia,
         sin_match.
    """
    empleados = list(empleados)
    nombre_normalizado = _normalizar_nombre(nombre_pdf)

    if dni_pdf:
        dni_normalizado = _normalizar_dni(dni_pdf)
        empleado_por_dni = next(
            (e for e in empleados if _normalizar_dni(e["dni_nie"]) == dni_normalizado), None
        )
        if empleado_por_dni is not None:
            score = fuzz.token_sort_ratio(nombre_normalizado, _normalizar_nombre(empleado_por_dni["nombre_completo"]))
            metodo = "dni_exacto" if score >= UMBRAL_ALERTA_NOMBRE else "dni_con_alerta_nombre"
            return ResultadoMatch(empleado=empleado_por_dni, metodo=metodo, score_nombre=score)

        # DNI con formato válido pero que no corresponde a ningún empleado de la BD.
        # Puede ser un DNI mal leído del PDF (el OCR cambia a veces la letra de control,
        # p.ej. 54413522F -> 54413522E). Si el nombre coincide fuerte con una ficha, se
        # sugiere con alerta para confirmación manual — nunca se usa el DNI del PDF como
        # contraseña en ese caso (lo decide main.py con `empleado_dni`). Sin coincidencia
        # fuerte de nombre, sin_match.
        mejor_empleado, mejor_score = _mejor_candidato_por_nombre(nombre_normalizado, empleados)
        if mejor_score >= umbral_fuzzy:
            return ResultadoMatch(
                empleado=mejor_empleado, metodo="dni_dudoso_nombre_coincide", score_nombre=mejor_score
            )
        return ResultadoMatch(empleado=mejor_empleado, metodo="sin_match", score_nombre=mejor_score)

    mejor_empleado, mejor_score = _mejor_candidato_por_nombre(nombre_normalizado, empleados)
    if mejor_score >= umbral_fuzzy:
        return ResultadoMatch(empleado=mejor_empleado, metodo="fuzzy_nombre", score_nombre=mejor_score)
    return ResultadoMatch(empleado=mejor_empleado, metodo="sin_match", score_nombre=mejor_score)
