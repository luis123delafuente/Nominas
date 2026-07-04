# Contexto del proyecto: automatización de envío de nóminas — MEDIFORM PLUS

## Rol y forma de trabajar

Actúa como ingeniero de software senior. Este proyecto se construye **por fases**, no de una sola vez.
Reglas de trabajo:

1. No avances a la siguiente fase sin que yo confirme explícitamente que la anterior funciona.
2. Al terminar cada fase: resume qué se implementó, cómo probarlo (comandos exactos), y qué archivos se tocaron. Luego espera.
3. Si algo en este documento es ambiguo o no cuadra con lo que ves en el código/PDF de ejemplo, pregúntame antes de asumir.
4. No instales ni sugieras librerías de pago ni servicios en la nube. Todo corre 100% local.
5. Prioriza código simple y legible sobre abstracciones prematuras — esta es una herramienta interna para una empresa pequeña (~25 empleados), no un producto SaaS.

## Contexto de negocio

Soy desarrollador freelance. Mi cliente es el fundador de MEDIFORM PLUS S.L. (consultoría, ~25 empleados).
Cada mes:
1. La gestoría le envía un único PDF con las nóminas de todos los trabajadores juntas.
2. Él separa manualmente cada nómina en un PDF individual.
3. Pone una contraseña a cada PDF (dato sensible: salario, DNI, IBAN...).
4. Lo envía por correo a cada trabajador desde Mail.app (Apple Mail, en macOS).

Esto le quita mucho tiempo cada mes y quiere automatizarlo, pero con un paso de revisión manual antes de que se envíe nada (no quiere una caja negra que envíe sin supervisión).

## Objetivo

Una aplicación web pequeña, de uso **exclusivamente local en su Mac**, con tres pantallas:
1. Subir el PDF mensual de la gestoría.
2. Revisar la lista de nóminas detectadas/emparejadas con sus empleados antes de enviar.
3. Gestionar la ficha de empleados (alta, edición, baja — hay rotación de personal).

No hay despliegue en servidor ni acceso remoto: se arranca con doble clic y se usa en `localhost`.

## Decisiones de arquitectura ya tomadas

Estas decisiones ya están tomadas con el cliente. No las cuestiones salvo que encuentres un problema técnico real (en ese caso, dímelo y lo valoramos juntos):

- **Backend**: Python 3.11+, FastAPI.
- **Frontend**: HTML server-side con Jinja2 + JS mínimo (nada de build de React/Vue — es una herramienta interna de 3 pantallas).
- **Base de datos**: SQLite (un solo archivo, `data/nominas.db`). No usar Excel como fuente de verdad: hay que poder dar de alta/baja empleados desde la propia app.
- **Extracción/split de PDF**: `PyMuPDF` (`fitz`) para extraer texto y anclar límites entre nóminas; `pypdf` para generar los PDFs individuales.
- **Cifrado del PDF individual**: `pypdf`, cifrado AES. Contraseña = DNI/NIE del trabajador tal cual aparece en la nómina (mayúsculas, sin espacios). Esto es una decisión consciente del cliente — ya se le planteó la alternativa de una contraseña más robusta y prefirió mantener el DNI. No lo cuestiones ni lo cambies.
- **Matching nombre-PDF ↔ empleado-BD**: `rapidfuzz`, porque el nombre en el PDF puede venir en distinto orden/formato que en la ficha del empleado (ej. "ALCALDE LASAOSA, NICOLAS" vs "Nicolás Alcalde Lasaosa").
- **Envío de correo**: Mail.app de macOS, controlado vía AppleScript (`osascript` desde Python con `subprocess`). Nada de Outlook, nada de SMTP genérico — así lo pidió el cliente porque es la app que ya usan.
- **Arranque**: un archivo `.command` de doble clic que levanta el servidor FastAPI y abre el navegador en `http://localhost:8000`.

## Estructura de carpetas objetivo

```
nominas-mediformplus/
├── app/
│   ├── main.py              # FastAPI app + rutas
│   ├── db.py                 # SQLite: conexión, esquema, queries
│   ├── pdf_parser.py         # detectar y separar nóminas del PDF maestro
│   ├── matcher.py            # emparejar nombre extraído del PDF -> empleado en BD
│   ├── crypto.py              # cifrado de cada PDF individual (pypdf, password = DNI)
│   ├── mailer_macos.py       # generación y ejecución de AppleScript para Mail.app
│   └── templates/
│       ├── subir.html
│       ├── revisar.html
│       └── empleados.html
├── data/
│   └── nominas.db
├── entrada/                  # aquí se coloca el PDF mensual de la gestoría
├── salida/                   # PDFs individuales cifrados generados
├── logs/                     # registro de envíos
├── tests/
│   ├── test_pdf_parser.py
│   └── test_matcher.py
├── Iniciar_App.command
├── requirements.txt
└── CLAUDE.md                 # este archivo
```

## Modelo de datos (SQLite)

**Tabla `empleados`**
- `id` (PK, autoincrement)
- `nombre_completo` (texto, tal como debe compararse contra el PDF)
- `dni_nie` (texto, único)
- `email` (texto)
- `activo` (booleano, default true — no borrar empleados, marcar inactivo para conservar histórico)
- `fecha_alta` (fecha)
- `fecha_baja` (fecha, nullable)

**Tabla `envios_log`**
- `id` (PK, autoincrement)
- `fecha_hora` (timestamp)
- `mes_nomina` (texto, ej. "2026-06")
- `empleado_id` (FK a empleados)
- `email_destino` (texto)
- `estado` (enum: enviado / error / omitido)
- `detalle` (texto, mensaje de error si aplica)

## Formato del PDF de la gestoría (observaciones sobre el archivo de ejemplo)

Tengo un PDF real de ejemplo (`NOMINAS_062026.pdf`, nóminas de junio de 2026, 25 trabajadores) que usaremos para desarrollar y probar el parser. Patrones observados que deben servir de ancla para separar cada nómina (hay que confirmarlos contra el PDF real, no solo contra el texto ya extraído):

- Cada nómina repite la cabecera `NIF. B82827635` (el NIF de la propia empresa MEDIFORM PLUS, se repite igual en todas — no confundir con el DNI del trabajador) justo antes del bloque "EMPRESA / DOMICILIO / Nº INS. S.S.".
- La fila `TRABAJADOR/A` contiene el nombre completo en mayúsculas (formato "APELLIDOS, NOMBRE"), y en la misma fila o la fila `D.N.I.` aparece el DNI/NIE del trabajador — ese es el dato que se usará como contraseña de cifrado.
- Cada nómina cierra con la sección `DETERMINACIÓN DE LAS B. DE COTIZACIÓN...` seguida de las líneas `3. Cotización adicional horas extraordinarias` y `4. Cotización adicional de solidaridad` — buen marcador de fin de bloque.
- El PDF puede contener tanto la representación tabular como un volcado de texto plano duplicado del mismo contenido (esto es un artefacto de cómo yo he leído el PDF, no está confirmado que exista en el binario original — hay que verificarlo abriendo el PDF real con PyMuPDF antes de dar por buena esta suposición).

**No asumas que este formato es 100% estable de un mes a otro.** El parser debe fallar de forma clara y visible (no en silencio) si no encuentra los anclajes esperados en un trabajador concreto, para que se revise a mano ese caso en la pantalla de revisión.

## Plan por fases (ir de una en una, confirmando antes de seguir)

- **Fase 0** — Scaffold: estructura de carpetas, entorno virtual, `requirements.txt`, FastAPI mínimo que responda en `/`.
- **Fase 1** — Parser: extraer y separar el PDF maestro en PDFs individuales (sin cifrar todavía), usando el PDF de ejemplo. Validar manualmente que cada PDF resultante contiene exactamente una nómina completa y correcta.
- **Fase 2** — Base de datos: esquema SQLite + CRUD de empleados (sin UI todavía, con tests).
- **Fase 3** — Matching: emparejar el nombre extraído en la Fase 1 contra los empleados de la Fase 2. Tests con casos límite (nombres con tildes, orden de apellidos distinto, sin coincidencia).
- **Fase 4** — Cifrado: aplicar contraseña (DNI) a cada PDF individual ya emparejado.
- **Fase 5** — UI de revisión: pantalla "subir PDF" → tabla de resultados (emparejado / sin match / sin email) con vista previa → checkbox de confirmación → botón enviar (sin enviar de verdad todavía, solo simular).
- **Fase 6** — Integración real con Mail.app vía AppleScript + registro en `envios_log`. (Esta fase requiere probarse en el Mac real, yo no puedo validar AppleScript en mi entorno de desarrollo).
- **Fase 7** — UI de gestión de empleados (alta/edición/baja) + `Iniciar_App.command` + manual de uso de una página.

Empezamos por la Fase 0.