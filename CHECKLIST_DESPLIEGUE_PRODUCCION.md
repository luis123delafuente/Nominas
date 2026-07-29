# Checklist de despliegue a producción — Nóminas MEDIFORM PLUS (Fase 3)

Para pasar de modo prueba a modo producción en el Mac del cliente de forma segura,
tanto para el envío de email como para la generación del fichero SEPA. Pensado para
seguirse paso a paso, en persona o en remoto, la próxima vez que se despliegue o
actualice el sistema en el Mac real.

No es una lista genérica de buenas prácticas: cada bloque responde a un problema que
ya ocurrió en el despliegue original de este proyecto (versión de Python, rutas de
iCloud, bloqueos de seguridad de macOS) más el nuevo riesgo que añade la Fase 3 (que
ahora sí se puede generar un fichero que mueve dinero real).

---

## 0. Antes de tocar el Mac del cliente

- [ ] Confirmar que la suite de tests pasa en local antes de copiar nada:
  `./venv/bin/python3 -m pytest -q` → debe decir `150 passed` (o el número vigente),
  0 fallos.
- [ ] Confirmar que `entrada/`, `data/*.db` y `data/clave_cifrado.key` **no** se copian
  al Mac del cliente por error (son del entorno de desarrollo, con datos de prueba).
  Solo se copia el código: `app/`, `scripts/`, `schemas/`, `tests/`,
  `requirements.txt`, `Iniciar_App.command`, los `.md`, y `config.local.example.py`
  (nunca `config.local.py`, que es personal de cada máquina y está en `.gitignore`).

---

## 1. Ubicación del proyecto — evitar la inestabilidad de iCloud (ya nos pasó)

El problema original: si la carpeta del proyecto vive dentro de una ubicación
sincronizada con iCloud Drive (típicamente `Desktop` o `Documents` si el cliente tiene
activado "Sincronizar Mac de escritorio y Carpeta Documentos" en Ajustes → [su nombre]
→ iCloud), macOS puede renombrar, mover o "evaporar" temporalmente archivos mientras
sincroniza (sobre todo con "Optimizar almacenamiento de Mac" activado, que borra la
copia local y la sustituye por un placeholder hasta que se vuelve a pedir). Esto rompió
el arranque en el despliegue original.

- [ ] Verificar en el Mac del cliente: Ajustes del Sistema → [nombre del usuario] →
  iCloud → si "Escritorio y Documentos" está activado, **no** instalar el proyecto
  dentro de `~/Desktop` ni `~/Documents`. Usar en su lugar una carpeta local no
  sincronizada, por ejemplo `~/Aplicaciones-Locales/nominas-mediformplus/` (crearla si
  no existe).
- [ ] Si por lo que sea el proyecto ya está dentro de una carpeta sincronizada,
  comprobar que la carpeta entera se ve como "descargada" (icono de nube tachada, no
  de nube con flecha) antes de arrancar la app — si no, forzar la descarga completa
  primero (clic derecho → "Descargar ahora" en Finder).
- [ ] Confirmar que `Iniciar_App.command` usa `python3 -m uvicorn ...` (ya corregido en
  el commit `b9573b1`) y no un shebang con ruta fija al venv — esto ya lo hace
  resistente a que la carpeta se mueva o se renombre después, pero sigue sin ser
  resistente a que iCloud la deje a medio sincronizar. La regla de oro sigue siendo:
  **fuera de iCloud**.

---

## 2. Versión de Python — evitar el problema de versión que ya tuvimos

- [ ] Comprobar la versión de Python del sistema: `python3 --version` → debe ser
  **3.11 o superior** (requisito del proyecto, ver `CLAUDE.md`). Si el Mac trae una
  versión más antigua (frecuente en Macs que no se han actualizado en tiempo), instalar
  una versión moderna con `python3` disponible en el `PATH` antes de continuar (por
  ejemplo desde python.org — no usar Homebrew si el cliente no lo tiene ya, para no
  añadir una dependencia de gestión de paquetes que luego haya que mantener).
- [ ] Recrear el entorno virtual **en el propio Mac del cliente** (no copiar `venv/` de
  otro ordenador — los binarios compilados de `cryptography`/`pymupdf` no son
  portables entre arquitecturas ni versiones de Python):
  ```
  cd ~/Aplicaciones-Locales/nominas-mediformplus
  python3 -m venv venv
  ./venv/bin/pip install -r requirements.txt
  ```
- [ ] Verificar que la instalación de dependencias termina sin errores de compilación.
  Si `cryptography`, `pymupdf` o `lxml`-like packages piden Xcode Command Line Tools,
  instalarlas con `xcode-select --install` y repetir — esto ya no debería hacer falta
  con las versiones actuales (vienen con wheels precompilados para macOS), pero
  conviene comprobarlo la primera vez en un Mac nuevo.
- [ ] Arrancar una vez a mano para confirmar que no hay errores de import:
  `./venv/bin/python3 -c "import app.main"` antes de usar `Iniciar_App.command`.

---

## 3. Bloqueos de seguridad de macOS — los tres que ya nos bloquearon antes

### 3.1 Gatekeeper / "no se puede abrir porque es de un desarrollador no identificado"

Si el proyecto ha llegado al Mac del cliente comprimido en un .zip, por AirDrop, o
descargado de algún sitio, macOS marca **todos** los archivos con el atributo de
cuarentena, incluido `Iniciar_App.command` (un script no firmado).

- [ ] Si al hacer doble clic en `Iniciar_App.command` aparece el aviso de
  "desarrollador no identificado": clic derecho sobre el archivo → **Abrir** (no doble
  clic) → confirmar en el diálogo. Esto solo hace falta la primera vez.
- [ ] Alternativa si el problema persiste en varios archivos: en Terminal,
  `xattr -cr ~/Aplicaciones-Locales/nominas-mediformplus` (quita la cuarentena de toda
  la carpeta de una vez).

### 3.2 Permiso de Automatización para controlar Mail.app

El envío de correo usa AppleScript (`osascript`) para controlar Mail.app. La primera
vez que se intenta enviar una nómina, macOS muestra un diálogo pidiendo permiso a
"Terminal" (o a la app que ejecuta el script) para controlar "Mail". Si se rechaza o se
ignora ese diálogo, los envíos fallan en silencio con un error de AppleScript.

- [ ] Aceptar explícitamente ese diálogo la primera vez que se pruebe un envío (aunque
  sea en modo prueba).
- [ ] Si se rechazó por error, o si no aparece porque un permiso previo quedó denegado:
  Ajustes del Sistema → Privacidad y Seguridad → Automatización → buscar "Terminal" (o
  la app correspondiente) en la lista → activar la casilla junto a "Mail".
- [ ] Confirmar con un envío de prueba real (modo prueba, ver sección 4) que el correo
  llega a `EMAIL_PRUEBA` con el PDF adjunto y cifrado.

### 3.3 Puerto 8000 ocupado por un proceso anterior que no se cerró bien

Si una sesión anterior de la app no se cerró limpiamente (se cerró la ventana de
Terminal en vez de pulsar Ctrl+C), el proceso de `uvicorn` puede quedar "zombie"
ocupando el puerto 8000, y el siguiente arranque falla o parece no hacer nada.

- [ ] Si `Iniciar_App.command` no abre nada en el navegador tras unos segundos:
  `lsof -i :8000` en Terminal para ver si hay un proceso Python ya escuchando ahí, y
  si lo hay, `kill <PID>` antes de reintentar.

---

## 4. Verificación en modo prueba (obligatoria antes de tocar el modo producción)

No saltarse este bloque aunque el cliente tenga prisa: es la última red de seguridad
antes de mover dinero o datos reales de los tres empleados/empresas.

- [ ] Crear `config.local.py` en el Mac del cliente a partir de
  `config.local.example.py`, con `MODO_ENVIO = "prueba"` y `EMAIL_PRUEBA` puesto al
  email real del cliente (nunca el del desarrollador, y nunca vacío — sin esto la app
  ya cae a modo prueba por defecto, pero sin `EMAIL_PRUEBA` el envío falla con un
  error claro en vez de arriesgarse a enviar a cualquier sitio).
- [ ] Dar de alta las tres empresas reales con `scripts/crear_empresa.py` (nombre y NIF
  reales, no los del NIF de pruebas).
- [ ] Dar de alta una cuenta bancaria real por empresa con
  `scripts/gestionar_cuenta_bancaria.py alta <NIF> <IBAN> <BIC>` — el IBAN/BIC reales
  de cada empresa, no valores inventados.
- [ ] Importar o dar de alta los empleados reales (con su email real e IBAN real si se
  va a probar también el SEPA).
- [ ] Subir un PDF real de una gestoría, confirmar en la pantalla de revisión que:
  - el matching por DNI encuentra a los empleados correctos,
  - el líquido a percibir sale autoextraído (etiqueta verde "Autoextraído") para las
    filas esperadas,
  - el badge de modo sigue en "🧪 PRUEBA".
- [ ] Confirmar el envío de esa nómina de prueba: el correo debe llegar a
  `EMAIL_PRUEBA`, con el asunto marcado `[PRUEBA] destinatario real: ...`, el PDF
  adjunto se abre con la contraseña (DNI) correcta.
- [ ] Generar el fichero SEPA de esa misma empresa en modo prueba: debe **fallar** con
  el mensaje `GeneracionBloqueadaPorModoPrueba` y **no** debe aparecer ningún
  `SEPA_*.xml` en `salida/<NIF>/<mes>/`. Si se genera igualmente, **no continuar** —
  hay una regresión real que hay que resolver antes de ir a producción.
- [ ] Repetir la subida + revisión para las otras dos empresas (al menos comprobar que
  el desplegable de empresa las lista y que cada una separa correctamente sus propias
  nóminas).

---

## 5. Copia de seguridad de la clave de cifrado — antes de generar ningún IBAN real

`data/clave_cifrado.key` se genera sola la primera vez que se cifra un IBAN o BIC (ver
`app/crypto_campos.py`). **Si se pierde este archivo, los IBAN/BIC ya guardados dejan
de poder leerse — no hay clave de recuperación alternativa** (decisión consciente de
la Fase 1, ver `CLAUDE.md`).

- [ ] En cuanto exista `data/clave_cifrado.key` en el Mac del cliente (tras el primer
  IBAN/cuenta bancaria real dado de alta), hacer una copia de seguridad en un sitio
  seguro y distinto del propio Mac (gestor de contraseñas del cliente, o un USB
  guardado bajo llave — nunca por email ni en una nube sin cifrar).
- [ ] Anotar en ese mismo sitio seguro (no en el propio proyecto) que esa clave
  corresponde a `data/nominas.db` de este Mac, con la fecha.
- [ ] Repetir la copia de seguridad si alguna vez se regenera la clave (borrado
  accidental, cambio de Mac, etc. — en ese caso los IBAN antiguos habrá que
  volver a introducirlos a mano, avisar al cliente de esto si ocurre).

---

## 6. Paso a modo producción

- [ ] Con el bloque 4 superado sin sorpresas, editar `config.local.py` en el Mac del
  cliente: `MODO_ENVIO = "produccion"`.
- [ ] Reiniciar la app (cerrar la ventana de Terminal y volver a abrir
  `Iniciar_App.command`) — la configuración se lee al arrancar cada request, pero es
  más seguro reiniciar para partir de un estado limpio.
- [ ] Confirmar visualmente en la pantalla de revisión que el badge cambia a
  "🚨 PRODUCCIÓN" antes de la primera confirmación de envío real.
- [ ] **Primer envío real supervisado**: hacerlo con el cliente delante (o por
  videollamada), con la nómina de un solo empleado de confianza si es posible, y
  confirmar que llega correctamente antes de procesar el lote completo del mes.
- [ ] **Primer fichero SEPA real supervisado**: generarlo, y antes de que el cliente lo
  suba a la banca online, comprobar juntos a mano que:
  - el `CtrlSum` (importe total) del fichero coincide con la suma de líquidos a
    percibir que el cliente esperaba ese mes para esa empresa,
  - el número de transacciones coincide con el número de empleados que tocaba pagar,
  - el fichero sigue guardado en `salida/<NIF>/<mes>/SEPA_<mes>.xml` para tener un
    registro local de lo generado.
- [ ] Recordar al cliente, explícitamente, que la subida del fichero a la banca online
  es manual y suya — el sistema no se conecta a ningún banco ni ejecuta la
  transferencia (esto no es negociable, ver `ROADMAP_NOMINAS.md`). Pedirle que revise
  el resumen que le muestre el propio banco antes de confirmar el pago ahí.

---

## 7. Plan de vuelta atrás

Si algo falla durante el primer uso real (bloque 6):

- [ ] Volver `MODO_ENVIO` a `"prueba"` en `config.local.py` inmediatamente — esto por
  sí solo ya bloquea cualquier envío de email real y cualquier generación de fichero
  SEPA real, sin tener que tocar nada más.
- [ ] Si ya se generó un fichero SEPA real por error: **no** debe subirse al banco.
  Borrarlo o moverlo fuera de `salida/` y avisar al cliente de que ese fichero en
  concreto no es válido para usar.
- [ ] Si ya se envió un email real por error: avisar al empleado afectado y, si aplica,
  reenviar la corrección — el histórico en `envios_log` deja constancia de la fecha y
  el destinatario real de cada envío para poder rastrearlo.
