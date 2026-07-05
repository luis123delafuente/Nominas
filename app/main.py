import io
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader

from app.config import cargar_configuracion
from app.crypto import cifrar_paginas
from app.db import (
    actualizar_empleado,
    crear_empleado,
    dar_baja_empleado,
    get_connection,
    listar_empleados,
    listar_empresas,
    obtener_empleado,
    obtener_empresa,
    obtener_envio_previo,
    reactivar_empleado,
)
from app.mailer_macos import enviar_nomina
from app.matcher import emparejar_nomina
from app.pdf_parser import (
    DNI_NIE_PATTERN,
    ParserError,
    SinNominasDetectadas,
    detectar_nominas,
    extraer_paginas_bytes,
    nombre_archivo_seguro,
)

MES_NOMINA_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

BASE_DIR = Path(__file__).resolve().parent.parent
ENTRADA_DIR = BASE_DIR / "entrada"
SALIDA_DIR = BASE_DIR / "salida"

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection()  # asegura el esquema/migraciones al arrancar la app de verdad
    conn.close()
    yield


app = FastAPI(title="Nominas MEDIFORM PLUS", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


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
    envio_previo_fecha: str | None  # fecha del último envío "enviado" a este empleado (en esta empresa) este mes, si lo hubo
    incluir_por_defecto: bool


@dataclass
class LoteRevision:
    ruta_pdf_maestro: str
    mes_nomina: str
    empresa_id: int
    filas: list[FilaRevision] = field(default_factory=list)


estado_actual: LoteRevision | None = None


@app.get("/")
def index(request: Request):
    mes_actual = datetime.now().strftime("%Y-%m")
    conn = get_connection()
    try:
        empresas = listar_empresas(conn, solo_activas=True)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "subir.html",
        {"error": None, "mes_nomina_por_defecto": mes_actual, "empresas": empresas, "empresa_id_seleccionada": None},
    )


@app.post("/subir")
def subir_pdf(
    request: Request, pdf: UploadFile = File(...), mes_nomina: str = Form(...), empresa_id: int = Form(...)
):
    global estado_actual

    conn = get_connection()
    try:
        empresas = listar_empresas(conn, solo_activas=True)
        empresa = obtener_empresa(conn, empresa_id)
    finally:
        conn.close()

    contexto_error = {"mes_nomina_por_defecto": mes_nomina, "empresas": empresas, "empresa_id_seleccionada": empresa_id}

    if empresa is None:
        return templates.TemplateResponse(
            request, "subir.html", {**contexto_error, "error": "La empresa seleccionada no es válida."}, status_code=400
        )

    if not MES_NOMINA_PATTERN.match(mes_nomina):
        return templates.TemplateResponse(
            request,
            "subir.html",
            {**contexto_error, "error": f"Mes de nómina inválido: '{mes_nomina}' (formato esperado AAAA-MM)"},
            status_code=400,
        )

    ENTRADA_DIR.mkdir(parents=True, exist_ok=True)
    ruta_maestro = ENTRADA_DIR / pdf.filename
    with open(ruta_maestro, "wb") as f:
        f.write(pdf.file.read())

    try:
        nominas = detectar_nominas(str(ruta_maestro), empresa["nif"])
    except SinNominasDetectadas as exc:
        mensaje = (
            f"No se ha detectado ninguna nómina de {empresa['nombre']} en este archivo — "
            "revisa que sea el PDF correcto de la gestoría."
        )
        if exc.nif_alternativo:
            mensaje += (
                f" (Se ha detectado un NIF distinto: {exc.nif_alternativo} — ¿has seleccionado la empresa correcta?)"
            )
        return templates.TemplateResponse(request, "subir.html", {**contexto_error, "error": mensaje}, status_code=400)
    except ParserError as exc:
        return templates.TemplateResponse(request, "subir.html", {**contexto_error, "error": str(exc)}, status_code=400)

    conn = get_connection()
    try:
        empleados_activos = listar_empleados(conn, solo_activos=True)

        filas = []
        for i, nomina in enumerate(nominas, start=1):
            resultado = emparejar_nomina(nomina.nombre_trabajador, nomina.dni_nie, empleados_activos)
            empleado = resultado.empleado
            empleado_id = empleado["id"] if empleado is not None else None

            envio_previo_fecha = None
            if empleado_id is not None:
                envio_previo = obtener_envio_previo(conn, empleado_id, empresa["id"], mes_nomina)
                if envio_previo is not None:
                    envio_previo_fecha = envio_previo["fecha_hora"]

            filas.append(
                FilaRevision(
                    numero=i,
                    nombre_pdf=nomina.nombre_trabajador,
                    dni_pdf=nomina.dni_nie,
                    pagina_inicio=nomina.pagina_inicio,
                    pagina_fin=nomina.pagina_fin,
                    metodo=resultado.metodo,
                    score_nombre=resultado.score_nombre,
                    empleado_id=empleado_id,
                    empleado_nombre=empleado["nombre_completo"] if empleado is not None else None,
                    empleado_email=empleado["email"] if empleado is not None else None,
                    empleado_dni=empleado["dni_nie"] if empleado is not None else None,
                    envio_previo_fecha=envio_previo_fecha,
                    incluir_por_defecto=(resultado.metodo == "dni_exacto" and envio_previo_fecha is None),
                )
            )
    finally:
        conn.close()

    estado_actual = LoteRevision(
        ruta_pdf_maestro=str(ruta_maestro), mes_nomina=mes_nomina, empresa_id=empresa["id"], filas=filas
    )
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
                estado_actual.empresa_id,
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


def _valores_formulario_vacios() -> dict:
    return {"id": "", "nombre_completo": "", "dni_nie": "", "email": ""}


@app.get("/empleados")
def empleados_vista(
    request: Request,
    mostrar_baja: bool = False,
    editar_id: int | None = None,
    mensaje: str | None = None,
):
    conn = get_connection()
    try:
        empleados = listar_empleados(conn, solo_activos=not mostrar_baja)

        valores = _valores_formulario_vacios()
        if editar_id is not None:
            empleado = obtener_empleado(conn, editar_id)
            if empleado is not None:
                valores = {
                    "id": str(empleado["id"]),
                    "nombre_completo": empleado["nombre_completo"],
                    "dni_nie": empleado["dni_nie"],
                    "email": empleado["email"],
                }
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "empleados.html",
        {
            "empleados": empleados,
            "mostrar_baja": mostrar_baja,
            "valores": valores,
            "mensaje": mensaje,
            "error": None,
        },
    )


@app.post("/empleados/guardar")
def empleados_guardar(
    request: Request,
    empleado_id: str = Form(""),
    nombre_completo: str = Form(...),
    dni_nie: str = Form(...),
    email: str = Form(...),
):
    nombre_completo = nombre_completo.strip()
    dni_nie_normalizado = dni_nie.strip().upper().replace(" ", "")
    email = email.strip()
    valores = {"id": empleado_id, "nombre_completo": nombre_completo, "dni_nie": dni_nie, "email": email}

    errores = []
    if not nombre_completo:
        errores.append("El nombre completo no puede estar vacío.")
    if not DNI_NIE_PATTERN.match(dni_nie_normalizado):
        errores.append(f"DNI/NIE con formato inválido: '{dni_nie}'.")
    if not EMAIL_PATTERN.match(email):
        errores.append(f"Email con formato inválido: '{email}'.")

    mensaje = None
    if not errores:
        conn = get_connection()
        try:
            if empleado_id:
                actualizar_empleado(
                    conn,
                    int(empleado_id),
                    nombre_completo=nombre_completo,
                    dni_nie=dni_nie_normalizado,
                    email=email,
                )
                mensaje = f"Empleado actualizado: {nombre_completo}"
            else:
                crear_empleado(conn, nombre_completo, dni_nie_normalizado, email, datetime.now().date().isoformat())
                mensaje = f"Empleado dado de alta: {nombre_completo}"
        except sqlite3.IntegrityError:
            accion = "otro empleado" if empleado_id else "un empleado"
            errores.append(f"Ya existe {accion} con el DNI {dni_nie_normalizado}.")
        finally:
            conn.close()

    if errores:
        conn = get_connection()
        try:
            empleados = listar_empleados(conn, solo_activos=True)
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "empleados.html",
            {
                "empleados": empleados,
                "mostrar_baja": False,
                "valores": valores,
                "mensaje": None,
                "error": " ".join(errores),
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/empleados?mensaje={quote(mensaje)}", status_code=303)


@app.post("/empleados/{empleado_id}/baja")
def empleados_dar_baja(empleado_id: int):
    conn = get_connection()
    try:
        empleado = obtener_empleado(conn, empleado_id)
        if empleado is None:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
        dar_baja_empleado(conn, empleado_id, datetime.now().date().isoformat())
        mensaje = f"Empleado dado de baja: {empleado['nombre_completo']}"
    finally:
        conn.close()

    return RedirectResponse(url=f"/empleados?mensaje={quote(mensaje)}", status_code=303)


@app.post("/empleados/{empleado_id}/reactivar")
def empleados_reactivar(empleado_id: int):
    conn = get_connection()
    try:
        empleado = obtener_empleado(conn, empleado_id)
        if empleado is None:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
        reactivar_empleado(conn, empleado_id)
        mensaje = f"Empleado reactivado: {empleado['nombre_completo']}"
    finally:
        conn.close()

    return RedirectResponse(url=f"/empleados?mensaje={quote(mensaje)}", status_code=303)
