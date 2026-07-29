import io
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader

from app.config import GeneracionBloqueadaPorModoPrueba, cargar_configuracion
from app.crypto import cifrar_paginas
from app.db import (
    actualizar_empleado,
    actualizar_iban_empleado,
    crear_empleado,
    dar_baja_empleado,
    descifrar_cuenta_bancaria,
    get_connection,
    listar_cuentas_bancarias,
    listar_empleados,
    listar_empresas,
    obtener_cuenta_bancaria,
    obtener_cuenta_predeterminada,
    obtener_empleado,
    obtener_empresa,
    obtener_envio_previo,
    obtener_iban_empleado,
    reactivar_empleado,
)
from app.mailer_smtp import enviar_nomina
from app.matcher import emparejar_nomina
from app.pdf_parser import (
    DNI_NIE_PATTERN,
    ParserError,
    SinNominasDetectadas,
    detectar_nominas,
    extraer_mes_nomina,
    extraer_paginas_bytes,
    nombre_archivo_seguro,
)
from app.sepa import ImporteInvalido, PagoSepa, generar_fichero_sepa, parsear_importe_a_centimos
from app.validaciones_bancarias import normalizar_iban, validar_iban

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
    liquido_a_percibir: str | None  # autoextraído del PDF si se pudo, si no None (cae al campo manual)
    liquido_metodo: str  # "autoextraido" / "manual" — honesto: solo "autoextraido" si se validó el formato


@dataclass
class LoteRevision:
    ruta_pdf_maestro: str
    mes_nomina: str
    empresa_id: int
    filas: list[FilaRevision] = field(default_factory=list)


estado_actual: LoteRevision | None = None


@app.get("/")
def index(request: Request):
    conn = get_connection()
    try:
        empresas = listar_empresas(conn, solo_activas=True)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "subir.html", {"error": None, "empresas": empresas, "empresa_id_seleccionada": None}
    )


@app.post("/subir")
def subir_pdf(request: Request, pdf: UploadFile = File(...), empresa_id: int = Form(...)):
    global estado_actual

    conn = get_connection()
    try:
        empresas = listar_empresas(conn, solo_activas=True)
        empresa = obtener_empresa(conn, empresa_id)
    finally:
        conn.close()

    contexto_error = {"empresas": empresas, "empresa_id_seleccionada": empresa_id}

    if empresa is None:
        return templates.TemplateResponse(
            request, "subir.html", {**contexto_error, "error": "La empresa seleccionada no es válida."}, status_code=400
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

    # El mes es una sugerencia, no un dato crítico: si no se puede leer del PDF
    # (formato inesperado en ese bloque concreto), caemos al mes actual del sistema
    # y el usuario lo corrige a mano en la propia pantalla de revisión.
    mes_nomina = extraer_mes_nomina(str(ruta_maestro), nominas[0].pagina_inicio) or datetime.now().strftime("%Y-%m")

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
                    liquido_a_percibir=nomina.liquido_a_percibir,
                    liquido_metodo="autoextraido" if nomina.liquido_a_percibir is not None else "manual",
                )
            )
    finally:
        conn.close()

    estado_actual = LoteRevision(
        ruta_pdf_maestro=str(ruta_maestro), mes_nomina=mes_nomina, empresa_id=empresa["id"], filas=filas
    )
    return RedirectResponse(url="/revisar", status_code=303)


def _valores_liquido_iniciales() -> dict:
    """Precarga el campo manual de líquido a percibir (Fase 2) con lo autoextraído del
    PDF cuando lo hubo (Fase 3) — sigue siendo un texto editable normal, el usuario
    puede corregirlo igual que si lo hubiera escrito él mismo desde cero."""
    return {
        fila.numero: fila.liquido_a_percibir or "" for fila in estado_actual.filas
    }


def _contexto_sepa(conn: sqlite3.Connection) -> dict:
    """Datos que necesita la sección de generación del fichero SEPA de revisar.html:
    las cuentas de pago activas de la empresa del lote, cuál es la predeterminada, y
    qué empleados tienen IBAN registrado (para avisar en la tabla antes de generar)."""
    cuentas_raw = listar_cuentas_bancarias(conn, estado_actual.empresa_id, solo_activas=True)
    predeterminada = obtener_cuenta_predeterminada(conn, estado_actual.empresa_id)
    ibans_disponibles = {
        fila.empleado_id: bool(obtener_iban_empleado(conn, fila.empleado_id))
        for fila in estado_actual.filas
        if fila.empleado_id is not None
    }
    return {
        "cuentas_bancarias": [descifrar_cuenta_bancaria(c) for c in cuentas_raw],
        "cuenta_id_seleccionada": predeterminada["id"] if predeterminada is not None else None,
        "ibans_disponibles": ibans_disponibles,
    }


@app.get("/revisar")
def revisar(request: Request):
    if estado_actual is None:
        return RedirectResponse(url="/")
    config = cargar_configuracion()
    conn = get_connection()
    try:
        contexto_sepa = _contexto_sepa(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "revisar.html",
        {
            "filas": estado_actual.filas,
            "mes_nomina": estado_actual.mes_nomina,
            "modo_envio": config.modo_envio,
            "resultados": None,
            "error_sepa": None,
            "valores_liquido": _valores_liquido_iniciales(),
            "sepa_incluidos": set(),
            **contexto_sepa,
        },
    )


@app.post("/revisar/mes_nomina")
def revisar_actualizar_mes(mes_nomina: str = Form(...)):
    """Corrige el mes sugerido (extraído del PDF) y recalcula los avisos de 'ya enviado'
    de toda la tabla — que dependen de (empresa_id, mes_nomina) juntos, nunca del mes solo."""
    global estado_actual
    if estado_actual is None:
        return RedirectResponse(url="/")

    if not MES_NOMINA_PATTERN.match(mes_nomina):
        return RedirectResponse(url="/revisar", status_code=303)

    conn = get_connection()
    try:
        nuevas_filas = []
        for fila in estado_actual.filas:
            envio_previo_fecha = None
            if fila.empleado_id is not None:
                envio_previo = obtener_envio_previo(conn, fila.empleado_id, estado_actual.empresa_id, mes_nomina)
                if envio_previo is not None:
                    envio_previo_fecha = envio_previo["fecha_hora"]

            nuevas_filas.append(
                replace(
                    fila,
                    envio_previo_fecha=envio_previo_fecha,
                    incluir_por_defecto=(fila.metodo == "dni_exacto" and envio_previo_fecha is None),
                )
            )
    finally:
        conn.close()

    estado_actual = replace(estado_actual, mes_nomina=mes_nomina, filas=nuevas_filas)
    return RedirectResponse(url="/revisar", status_code=303)


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

    reader = PdfReader(estado_actual.ruta_pdf_maestro)
    config = cargar_configuracion()

    conn = get_connection()
    try:
        empresa = obtener_empresa(conn, estado_actual.empresa_id)
        carpeta_salida = SALIDA_DIR / empresa["nif"] / estado_actual.mes_nomina
        carpeta_salida.mkdir(parents=True, exist_ok=True)

        resultados = []
        for fila in estado_actual.filas:
            if fila.metodo == "sin_match":
                continue  # nunca se puede forzar el envío de una nómina sin emparejar
            if fila.numero not in numeros_incluidos:
                continue

            password = fila.dni_pdf if fila.metodo in ("dni_exacto", "dni_con_alerta_nombre") else fila.empleado_dni
            nombre_archivo = f"{fila.numero:02d}_{nombre_archivo_seguro(fila.empleado_nombre)}.pdf"
            ruta_salida = carpeta_salida / nombre_archivo

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

        contexto_sepa = _contexto_sepa(conn)
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
            "error_sepa": None,
            "valores_liquido": _valores_liquido_iniciales(),
            "sepa_incluidos": set(),
            **contexto_sepa,
        },
    )


@app.post("/revisar/generar_sepa")
async def generar_sepa(request: Request):
    if estado_actual is None:
        return RedirectResponse(url="/")

    form = await request.form()
    cuenta_id_texto = form.get("cuenta_id", "")
    numeros_incluidos = {int(v) for v in form.getlist("sepa_incluir")}
    valores_liquido = {fila.numero: form.get(f"sepa_liquido_{fila.numero}", "") for fila in estado_actual.filas}

    config = cargar_configuracion()
    conn = get_connection()
    try:
        contexto_sepa = _contexto_sepa(conn)
        errores = []

        cuenta = None
        if not cuenta_id_texto:
            errores.append("Selecciona una cuenta bancaria de pago.")
        else:
            cuenta_row = obtener_cuenta_bancaria(conn, int(cuenta_id_texto))
            if (
                cuenta_row is None
                or cuenta_row["empresa_id"] != estado_actual.empresa_id
                or not cuenta_row["activa"]
            ):
                errores.append("La cuenta bancaria seleccionada no es válida.")
            else:
                cuenta = descifrar_cuenta_bancaria(cuenta_row)

        pagos = []
        for fila in estado_actual.filas:
            if fila.numero not in numeros_incluidos:
                continue
            if fila.empleado_id is None:
                errores.append(f"Fila {fila.numero}: no se puede incluir una nómina sin empleado emparejado.")
                continue

            try:
                importe_centimos = parsear_importe_a_centimos(valores_liquido.get(fila.numero, ""))
            except ImporteInvalido as exc:
                errores.append(f"{fila.empleado_nombre}: {exc}")
                continue

            iban_empleado = obtener_iban_empleado(conn, fila.empleado_id)
            if not iban_empleado:
                errores.append(f"{fila.empleado_nombre}: no tiene IBAN registrado en su ficha.")
                continue

            pagos.append(
                PagoSepa(
                    empleado_id=fila.empleado_id,
                    nombre=fila.empleado_nombre,
                    iban=iban_empleado,
                    importe_centimos=importe_centimos,
                    concepto=f"Nomina {estado_actual.mes_nomina}",
                    endtoend_id=f"NOM-{estado_actual.mes_nomina}-{fila.empleado_id}",
                )
            )

        if not errores and not pagos:
            errores.append("No se ha seleccionado ninguna nómina para incluir en el fichero SEPA.")

        xml_bytes = None
        if not errores:
            empresa = obtener_empresa(conn, estado_actual.empresa_id)
            carpeta_salida = SALIDA_DIR / empresa["nif"] / estado_actual.mes_nomina
            ruta_salida = carpeta_salida / f"SEPA_{estado_actual.mes_nomina}.xml"
            try:
                xml_bytes = generar_fichero_sepa(
                    config,
                    empresa["nombre"],
                    cuenta["iban"],
                    cuenta["bic"],
                    estado_actual.mes_nomina,
                    pagos,
                    str(ruta_salida),
                )
            except (GeneracionBloqueadaPorModoPrueba, ValueError) as exc:
                errores.append(str(exc))

        if errores:
            return templates.TemplateResponse(
                request,
                "revisar.html",
                {
                    "filas": estado_actual.filas,
                    "mes_nomina": estado_actual.mes_nomina,
                    "modo_envio": config.modo_envio,
                    "resultados": None,
                    "error_sepa": " ".join(errores),
                    "valores_liquido": valores_liquido,
                    "sepa_incluidos": numeros_incluidos,
                    **{**contexto_sepa, "cuenta_id_seleccionada": int(cuenta_id_texto) if cuenta_id_texto.isdigit() else contexto_sepa["cuenta_id_seleccionada"]},
                },
                status_code=400,
            )
    finally:
        conn.close()

    return StreamingResponse(
        io.BytesIO(xml_bytes),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="SEPA_{estado_actual.mes_nomina}.xml"'},
    )


def _valores_formulario_vacios() -> dict:
    return {"id": "", "nombre_completo": "", "dni_nie": "", "email": "", "iban": ""}


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
                    "iban": obtener_iban_empleado(conn, editar_id) or "",
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
    iban: str = Form(""),
):
    nombre_completo = nombre_completo.strip()
    dni_nie_normalizado = dni_nie.strip().upper().replace(" ", "")
    email = email.strip()
    iban = iban.strip()
    valores = {"id": empleado_id, "nombre_completo": nombre_completo, "dni_nie": dni_nie, "email": email, "iban": iban}

    errores = []
    if not nombre_completo:
        errores.append("El nombre completo no puede estar vacío.")
    if not DNI_NIE_PATTERN.match(dni_nie_normalizado):
        errores.append(f"DNI/NIE con formato inválido: '{dni_nie}'.")
    if not EMAIL_PATTERN.match(email):
        errores.append(f"Email con formato inválido: '{email}'.")
    if iban:
        try:
            validar_iban(normalizar_iban(iban))
        except ValueError as exc:
            errores.append(str(exc))

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
                actualizar_iban_empleado(conn, int(empleado_id), iban or None)
                mensaje = f"Empleado actualizado: {nombre_completo}"
            else:
                nuevo_id = crear_empleado(
                    conn, nombre_completo, dni_nie_normalizado, email, datetime.now().date().isoformat()
                )
                actualizar_iban_empleado(conn, nuevo_id, iban or None)
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
