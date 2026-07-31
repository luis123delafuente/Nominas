# Contexto global del proyecto — Sistema de automatización de nóminas

> Este documento existe para dar una imagen completa del proyecto antes de tocar código.
> No repite el README técnico — da el contexto de negocio y el orden de fases que hay
> detrás de las tareas que se van a ir pidiendo.

## Qué es esto, en una frase

Un sistema local (Python/FastAPI + SQLite, sin nube) que recibe el PDF mensual de
nóminas de una gestoría, separa cada nómina individual, la empareja con el empleado
correcto por DNI, permite revisión manual, la cifra y la envía por email — y que ahora
va a generar además el fichero de transferencia SEPA para el pago.

## Decisiones de negocio ya tomadas (no reabrir sin motivo)

- **100% local, sin SaaS.** Cada cliente tendrá su propio Mac y su propio SQLite. No hay
  servidor centralizado ni está previsto que lo haya a corto plazo. Esto es intencional:
  reduce la carga legal/RGPD y el riesgo de seguridad de concentrar IBANs de varias
  empresas en un solo servidor.
- **El sistema nunca ejecuta transferencias ni se conecta a ningún banco.** Solo genera
  un fichero que el cliente sube manualmente a su banco. Esta decisión de seguridad no
  es negociable ni un detalle de implementación menor.
- **Envío de email multiplataforma vía SMTP con la cuenta propia del cliente**
  (no un servicio transaccional de terceros tipo Postmark/SES). Decisión tomada:
  mantiene el email saliendo desde la cuenta real del cliente (igual que hoy con
  Mail.app), evita depender de configurar autenticación de dominio (SPF/DKIM) por
  cliente, y evita concentrar el envío de todos los clientes en una única cuenta/API
  key compartida — lo cual rompería el aislamiento de riesgo entre clientes que ya
  se mantiene en el resto de la arquitectura. Mail.app/AppleScript queda sustituido
  por `smtplib`, con la contraseña de aplicación del cliente cifrada con la misma
  capa Fernet ya construida para IBAN/BIC. Se implementa **después de entregar el
  SEPA al cliente actual** (Fase 3.5, ver abajo), no de forma condicional a que
  aparezca un cliente con Windows.
- **Target de comercialización futura: PYMEs de 30-100 empleados, sector no
  tecnológico, dentro de España.** No hay intención (por ahora) de expandirse fuera de
  la eurozona/España, así que no hay que prever otros esquemas de pago fuera de SEPA.
- **El parser de PDF es "un parser por gestoría", no un parser universal.** No se debe
  intentar generalizar el parsing hasta que exista un segundo cliente real con una
  gestoría distinta confirmada. Generalizar esto sin datos reales sería diseñar a
  ciegas.
- **Cliente actual = trabajo familiar (madre), sin presión de plazo.** Eso da margen
  para hacer bien el diseño genérico del SEPA sin prisa, pero no es excusa para
  descuidar la seguridad de los datos (IBAN) — el sistema sigue procesando datos reales
  de terceros (empleados).

## Qué SÍ se debe generalizar ya (aunque solo haya un cliente)

A diferencia del parser de PDF, estas piezas se generalizan desde el primer commit
porque el coste de hacerlo bien ahora es prácticamente el mismo que hacerlo específico,
y retrasarlo sale caro después:

- La tabla de empresas/NIFs (hoy hardcodeada).
- El generador SEPA (se apoya en un estándar internacional fijo — no hay variabilidad
  real que esperar, así que no hay excusa para no generalizarlo ya).
- El cifrado de campos sensibles (IBAN/BIC).

## Fases de trabajo

### Fase 0 — Decisión técnica previa (bloqueante)
Decidir la estrategia de cifrado en reposo para campos sensibles (IBAN, BIC) antes de
crear cualquier columna nueva en la base de datos. Opciones a evaluar: cifrado a nivel
de campo (ej. Fernet/AES-GCM aplicado antes de guardar) vs. SQLCipher para la base
completa. Esta decisión condiciona el esquema de las fases siguientes, así que va
primero.

### Fase 1 — Generalización de base
- Sacar del código el mapeo empresa↔NIF y convertirlo en una tabla configurable en BD
  (alta de empresas nuevas sin tocar código).
- Extender el modo prueba/producción para que cubra también la generación del fichero
  SEPA, no solo el envío de email — ningún test debe poder generar un fichero real
  subible al banco.
- Implementar el mecanismo de cifrado decidido en la Fase 0 para los campos que se
  añadirán en la Fase 2.

### Fase 2 — Funcionalidad de pago SEPA
- Añadir IBAN a la ficha del empleado (cifrado).
- Modelo de cuentas bancarias por empresa: varias cuentas posibles por empresa, IBAN/BIC
  cifrados, selección de cuenta en el momento de generar el fichero.
- Validación de IBAN/BIC con checksum real (ISO 7064 mod-97), no solo de formato.
- Generador de fichero SEPA XML, estándar ISO 20022 pain.001.001.03, a partir del
  "líquido a percibir" ya confirmado en la pantalla de revisión existente.

### Fase 2.5 — Extracción automática del "líquido a percibir"
El generador SEPA de la Fase 2 se construyó asumiendo el líquido a percibir como
campo manual editable en la pantalla de revisión, porque el dato no existía todavía
en `pdf_parser.py`. Se sustituye por extracción automática siguiendo el mismo patrón
de anclaje ya usado para NIF/DNI/periodo, por gestoría ya soportada, reutilizando el
sistema de confianza verde/ámbar/rojo existente. El campo manual no desaparece: sigue
siendo el fallback para cuando la extracción falla o para gestorías nuevas sin el
patrón añadido, y sigue siendo editable incluso cuando el valor viene autoextraído.

### Fase 3 — Validación y entrega al cliente actual
Parte de código completa: prueba end-to-end con PDFs reales de las tres empresas
(incluye el caso confirmado de empleado que cobra de más de una empresa el mismo
mes, sin mezcla de pagos), verificación del bloqueo de modo prueba en el recorrido
completo, y `CHECKLIST_DESPLIEGUE_PRODUCCION.md` con los pasos ligados a los
incidentes reales ya conocidos (iCloud, versión de Python, Gatekeeper, permiso de
Automatización, puerto zombie, copia de la clave de cifrado, plan de vuelta atrás).

Pendiente, no es trabajo de código:
- [ ] Prueba real de subida del fichero SEPA a la web del banco (importe simbólico).
- [ ] Ejecutar el despliegue en producción siguiendo el checklist.
- [x] Ubicación de la copia de la clave de cifrado: verificado que `data/clave_cifrado.key`
      aún no existe (0 IBANs y 0 cuentas bancarias guardadas en `nominas.db` a fecha de
      esta comprobación) — no hay nada que respaldar todavía. Procedimiento decidido para
      cuando se genere (al guardar el primer IBAN real): copiarla de inmediato a un gestor
      de contraseñas o a un pendrive físico aparte del Mac — nunca a iCloud/Desktop/
      Documentos, por los problemas de sincronización ya conocidos.

### Fase 3.5 — Envío de email multiplataforma
Completa: `app/mailer_smtp.py` sustituye a `mailer_macos.py` (eliminado, recuperable en
git), misma interfaz pública para minimizar el impacto en `main.py`. Credenciales SMTP
por empresa en tabla `credenciales_smtp`, contraseña cifrada con la misma capa Fernet
(`crypto_campos.py`). `resolver_destinatario()` sin tocar — modo prueba sigue
redirigiendo, no bloqueando. Sin dependencia de macOS/AppleScript (confirmado por
grep). `DOCUMENTO_CONTRASENA_APLICACION.md` creado para el alta no técnica en Gmail/
Outlook. 155/155 tests pasan.

Pendiente, no es trabajo de código:
- [x] `CHECKLIST_DESPLIEGUE_PRODUCCION.md` actualizado: quitado el paso de permiso de
      Automatización para Mail.app, añadida el alta de credenciales SMTP de las tres
      empresas como paso obligatorio, con verificación del fallo controlado si faltan.
      Mejora de higiene ya aplicada: la contraseña se pide de forma interactiva con
      `getpass.getpass()` en vez de recibirse como argumento — ya no queda en el
      historial del shell. Tests nuevos en `tests/test_gestionar_smtp_empresa.py`
      (no existían tests para ningún script de `scripts/` hasta ahora).
- [ ] Nota de consistencia, opcional: `scripts/gestionar_cuenta_bancaria.py` recibe
      el IBAN/BIC como argumento de línea de comandos, con el mismo problema menor de
      higiene que se acaba de corregir para la contraseña SMTP. Aplicar el mismo
      cambio (entrada interactiva) si se quiere tratar con el mismo criterio.
- [x] Confirmada la eliminación completa de `mailer_macos.py` — el nuevo método
      (`smtplib`, librería estándar de Python) funciona igual en Mac, Windows y Linux,
      sin dependencia añadida, así que no hace falta mantener un fallback específico
      de macOS.

### Fase 3.6 — OCR para PDFs escaneados
La gestoría envió un mes el PDF como escaneado (sin capa de texto), caso no previsto
hasta entonces. `app/ocr.py` ejecuta OCR local con el framework Vision de macOS (vía
`ocrmac`, sin coste ni dependencia de nube) sobre las páginas sin texto, devolviendo
pseudo-palabras con coordenadas en puntos PDF — mismo formato que
`page.get_text("words")`, así que el resto del parser (`app/pdf_parser.py`) no
distingue entre texto incrustado y OCR. Resultados cacheados en disco
(`data/ocr_cache/`, en `.gitignore`) por hash del PDF, para no repetir el OCR (~20-30s)
en cada reinicio con el mismo archivo.

El OCR introduce errores que el texto incrustado no tiene (tildes perdidas, `D.N.I.`
leído como `D.N.1.`, una letra de control del DNI mal reconocida): `pdf_parser.py`
compara cabeceras de forma tolerante (normalización + `rapidfuzz`, solo aplicada a las
cabeceras fijas, nunca a los datos extraídos) y `matcher.py` añade un tercer caso,
`dni_dudoso_nombre_coincide` — un DNI con formato válido pero ajeno a la BD, con el
nombre coincidiendo fuerte, se sugiere para confirmación manual en vez de descartarse
directo; la contraseña del PDF sigue siendo siempre la de la ficha, nunca el DNI del
PDF en ese caso. Revisado en detalle 2026-07-31: encontrado y corregido un fallo real
(no introducido por el OCR, preexistente pero mucho más probable con él) — una fila
`sin_match` puede traer igualmente un `empleado_id` relleno (mejor candidato fuzzy sin
confirmar, ver `matcher.py`), y la tabla de generación del SEPA no lo excluía ni en la
plantilla ni en el servidor, permitiendo en teoría incluir a esa persona sugerida (no
confirmada) en un pago SEPA si tenía IBAN. Corregido en `app/main.py` y
`app/templates/revisar.html`, con test de regresión. 168/168 tests pasan.

Pendiente, no es trabajo de código:
- [ ] `data/ocr_cache/` no tiene limpieza automática — crece con cada PDF escaneado
      distinto que se sube a lo largo de los años. Bajo impacto (unos pocos KB por
      página), revisar solo si algún día llega a pesar.

### Fase 4 — Preparación para comercializar (más adelante, no ahora)
No empezar hasta que exista interés real de un segundo cliente. Incluye: catálogo de
parsers por gestoría, contrato de licencia de software, modelo de soporte remoto, y
precio final ajustado con datos reales (rango orientativo ya calculado: alta
600-1.200€, mensual 100-250€ según número de empleados).

## Restricciones no negociables (aplican en todas las fases)

- Nunca conectar el sistema a ningún banco ni ejecutar transferencias automáticamente.
- Nunca permitir que el modo prueba genere ficheros reales (email o SEPA).
- No construir un parser de PDF "universal" ni anticipar gestorías no confirmadas.
- No usar un servicio de email transaccional de terceros compartido entre clientes
  (rompe el aislamiento de riesgo entre instalaciones). El envío multiplataforma se
  hace vía SMTP con la cuenta propia de cada cliente.
- No añadir soporte para esquemas de pago fuera de SEPA/España sin confirmación previa.
- Cualquier campo IBAN/BIC nuevo se guarda cifrado desde el primer commit, no en texto
  plano "temporalmente".
