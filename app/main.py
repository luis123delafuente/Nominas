import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader

from app.config import cargar_configuracion
from app.crypto import cifrar_paginas
from app.db import get_connection, listar_empleados
from app.mailer_macos import enviar_nomina
from app.matcher import emparejar_nomina
from app.pdf_parser import ParserError, detectar_nominas, extraer_paginas_bytes, nombre_archivo_seguro

MES_NOMINA_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

BASE_DIR = Path(__file__).resolve().parent.parent
ENTRADA_DIR = BASE_DIR / "entrada"
SALIDA_DIR = BASE_DIR / "salida"

app = FastAPI(title="Nominas MEDIFORM PLUS")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

get_connection().close()  # asegura el esquema/migraciones al arrancar la app


@dataclass
class FilaRevision:
    numero: int
    nombre_pdf: str
    dni_pdf: str | None
    pagina_inicio: int
    pagina_fin: int
    metodo: str  # dni_exacto / dni_con_alerta_nombre / fuzzy_nombre / sin_match
    score_nombre: float
    empleado_id: int | None
    empleado_nombre: str | None
    empleado_email: str | None
    empleado_dni: str | None
    incluir_por_defecto: bool


@dataclass
class LoteRevision:
    ruta_pdf_maestro: str
    mes_nomina: str
    filas: list[FilaRevision] = field(default_factory=list)


estado_actual: LoteRevision | None = None


@app.get("/")
def index(request: Request):
    mes_actual = datetime.now().strftime("%Y-%m")
    return templates.TemplateResponse(request, "subir.html", {"error": None, "mes_nomina_por_defecto": mes_actual})


@app.post("/subir")
def subir_pdf(request: Request, pdf: UploadFile = File(...), mes_nomina: str = Form(...)):
    global estado_actual

    if not MES_NOMINA_PATTERN.match(mes_nomina):
        return templates.TemplateResponse(
            request,
            "subir.html",
            {"error": f"Mes de nómina inválido: '{mes_nomina}' (formato esperado AAAA-MM)", "mes_nomina_por_defecto": mes_nomina},
            status_code=400,
        )

    ENTRADA_DIR.mkdir(parents=True, exist_ok=True)
    ruta_maestro = ENTRADA_DIR / pdf.filename
    with open(ruta_maestro, "wb") as f:
        f.write(pdf.file.read())

    try:
        nominas = detectar_nominas(str(ruta_maestro))
    except ParserError as exc:
        return templates.TemplateResponse(
            request, "subir.html", {"error": str(exc), "mes_nomina_por_defecto": mes_nomina}, status_code=400
        )

    conn = get_connection()
    try:
        empleados_activos = listar_empleados(conn, solo_activos=True)
    finally:
        conn.close()

    filas = []
    for i, nomina in enumerate(nominas, start=1):
        resultado = emparejar_nomina(nomina.nombre_trabajador, nomina.dni_nie, empleados_activos)
        empleado = resultado.empleado
        filas.append(
            FilaRevision(
                numero=i,
                nombre_pdf=nomina.nombre_trabajador,
                dni_pdf=nomina.dni_nie,
                pagina_inicio=nomina.pagina_inicio,
                pagina_fin=nomina.pagina_fin,
                metodo=resultado.metodo,
                score_nombre=resultado.score_nombre,
                empleado_id=empleado["id"] if empleado is not None else None,
                empleado_nombre=empleado["nombre_completo"] if empleado is not None else None,
                empleado_email=empleado["email"] if empleado is not None else None,
                empleado_dni=empleado["dni_nie"] if empleado is not None else None,
                incluir_por_defecto=(resultado.metodo == "dni_exacto"),
            )
        )

    estado_actual = LoteRevision(ruta_pdf_maestro=str(ruta_maestro), mes_nomina=mes_nomina, filas=filas)
    return RedirectResponse(url="/revisar", status_code=303)


@app.get("/revisar")
def revisar(request: Request):
    if estado_actual is None:
        return RedirectResponse(url="/")
    config = cargar_configuracion()
    return templates.TemplateResponse(
        request,
        "revisar.html",
        {
            "filas": estado_actual.filas,
            "mes_nomina": estado_actual.mes_nomina,
            "modo_envio": config.modo_envio,
            "resultados": None,
        },
    )


@app.get("/revisar/preview/{numero}")
def preview(numero: int):
    if estado_actual is None:
        raise HTTPException(status_code=404, detail="No hay ningún lote cargado")

    fila = next((f for f in estado_actual.filas if f.numero == numero), None)
    if fila is None:
        raise HTTPException(status_code=404, detail="Nómina no encontrada")

    reader = PdfReader(estado_actual.ruta_pdf_maestro)
    contenido = extraer_paginas_bytes(reader, fila.pagina_inicio, fila.pagina_fin)
    return StreamingResponse(io.BytesIO(contenido), media_type="application/pdf")


@app.post("/revisar/confirmar")
async def confirmar(request: Request):
    if estado_actual is None:
        return RedirectResponse(url="/")

    form = await request.form()
    numeros_incluidos = {int(v) for v in form.getlist("incluir")}

    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(estado_actual.ruta_pdf_maestro)
    config = cargar_configuracion()

    conn = get_connection()
    try:
        resultados = []
        for fila in estado_actual.filas:
            if fila.metodo == "sin_match":
                continue  # nunca se puede forzar el envío de una nómina sin emparejar
            if fila.numero not in numeros_incluidos:
                continue

            password = fila.dni_pdf if fila.metodo in ("dni_exacto", "dni_con_alerta_nombre") else fila.empleado_dni
            nombre_archivo = f"{fila.numero:02d}_{nombre_archivo_seguro(fila.empleado_nombre)}.pdf"
            ruta_salida = SALIDA_DIR / nombre_archivo

            cifrar_paginas(reader, range(fila.pagina_inicio, fila.pagina_fin + 1), str(ruta_salida), password)

            resultado = enviar_nomina(
                conn,
                fila.empleado_id,
                fila.empleado_nombre,
                fila.empleado_email,
                estado_actual.mes_nomina,
                str(ruta_salida),
                config,
            )
            resultados.append(resultado)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "revisar.html",
        {
            "filas": estado_actual.filas,
            "mes_nomina": estado_actual.mes_nomina,
            "modo_envio": config.modo_envio,
            "resultados": resultados,
        },
    )
