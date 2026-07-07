# Manual de uso — Nóminas MEDIFORM PLUS

Guía rápida del proceso mensual. No hace falta saber programar para seguirla.

## 1. Guarda el PDF de la gestoría

Hay tres empresas distintas: **MEDIFORM PLUS S.L.**, **MEDIFORMPLUS FORMACION SL** y **NUESTRAFARMA PLUS SL**. Cada una tiene su propia gestoría y su propio PDF mensual — son archivos separados, uno por empresa. No hay que combinarlos ni subirlos juntos: cada PDF se sube por separado, cada uno a su debido tiempo.

Cuando la gestoría de cualquiera de las tres empresas te envíe su PDF mensual con todas las nóminas juntas, guárdalo en tu ordenador (en cualquier carpeta, no importa dónde ni cómo lo llames).

## 2. Abre la aplicación

Haz doble clic en **`Iniciar_App.command`**. Se abrirá una ventana de terminal (no la cierres mientras uses la app) y, a los pocos segundos, se abrirá tu navegador automáticamente en la pantalla de subida.

Si el navegador no se abre solo, entra tú a mano en: `http://localhost:8000`

Para cerrar la aplicación cuando termines, cierra la ventana de terminal que se abrió (o pulsa Ctrl+C dentro de ella).

**Nota:** la primera vez que ejecutes `Iniciar_App.command` en un ordenador, macOS mostrará un aviso pidiendo permiso para controlar Mail.app. Hay que aceptarlo — si no, el envío de correos no funcionará. Solo lo pide esa primera vez.

## 3. Sube el PDF

En la pantalla inicial:
1. Elige primero, en el desplegable, la **empresa** a la que corresponde el PDF que vas a subir.
2. Elige el archivo PDF de la gestoría de esa empresa.
3. Pulsa "Subir y analizar".

Si por error eliges una empresa distinta a la del PDF que subes (por ejemplo, seleccionas MEDIFORM PLUS S.L. pero subes el PDF de NUESTRAFARMA PLUS SL), la aplicación lo detecta y te avisa con un error claro, indicando el NIF que sí ha encontrado en el archivo, en vez de mezclar los datos de una empresa con los de otra. Simplemente vuelve atrás y elige la empresa correcta.

Ya no hace falta escribir el mes de la nómina a mano: la aplicación lo detecta sola, leyendo el propio contenido del PDF. Si por lo que sea el mes detectado no fuera el correcto, se puede corregir después, ya en la pantalla de revisión (ver siguiente sección).

## 4. La pantalla de revisión: qué significa cada color

Arriba del todo verás el mes de la nómina que la aplicación ha detectado del propio PDF, en un campo editable con un botón **"Actualizar"** al lado. Si el mes no es correcto, escribe el correcto (formato AAAA-MM, por ejemplo `2026-06` para junio de 2026) y pulsa "Actualizar": la página se recarga y, si hace falta, se recalculan los avisos de "ya enviado" de toda la tabla según el mes corregido (ver más abajo).

La aplicación separa el PDF en una nómina por trabajador e intenta emparejar cada una con la ficha de un empleado. Cada fila de la tabla sale con un color:

- 🟢 **Verde (DNI exacto)** — el DNI de la nómina coincide exactamente con el de un empleado dado de alta. Está autoconfirmada; no tienes que hacer nada salvo que quieras excluirla (desmarcando su casilla).
- 🟡 **Ámbar (revisar a mano)** — hay algo que no cuadra del todo y necesita que lo mires tú antes de aprobarla:
  - *"DNI coincide pero el nombre no cuadra"*: el DNI de la nómina es el de un empleado concreto, pero el nombre que trae el PDF no se parece al de su ficha. Puede ser un error de tecleo en la ficha o un problema al leer el PDF. Compara los dos nombres que se muestran y, si de verdad es la misma persona, marca la casilla para incluirla; si no, corrige antes la ficha del empleado.
  - *"Coincidencia por nombre (sin DNI en la nómina)"*: esa nómina en concreto no traía un DNI legible, así que el emparejamiento se ha hecho solo por el nombre. Revisa que sea la persona correcta antes de marcar la casilla.
- 🔴 **Rojo (sin match)** — no se ha encontrado ningún empleado que corresponda a esa nómina. No se puede enviar hasta que lo arregles: normalmente porque el empleado todavía no está dado de alta (ve a "Gestión de empleados" y date de alta), o porque el DNI de su ficha tiene una errata.

Además, si a un empleado ya se le envió la nómina de esa empresa y ese mes en concreto, su fila muestra un aviso en azul: **"📨 Ya se envió el `<fecha y hora>`"**. En ese caso, la casilla de esa fila empieza **desmarcada a propósito** (para no reenviar sin querer algo que ya se mandó), pero sigue disponible: si la gestoría te envió una corrección y de verdad hace falta reenviar esa nómina, simplemente marca la casilla tú mismo.

Puedes pulsar "Ver" en cualquier fila para previsualizar el PDF de esa nómina (sin cifrar) antes de decidir.

Cuando estés conforme, pulsa **"Enviar"**. La aplicación cifra cada PDF confirmado con el DNI del trabajador como contraseña y lo envía por correo desde Mail.app. Al final verás un resumen de qué se envió y a quién (o el motivo si algo falló).

El correo sale siempre desde la cuenta que Mail.app tenga marcada como predeterminada en ese ordenador (Mail → Ajustes → Redacción). Si cambias esa cuenta predeterminada, cambiará también el remitente de las nóminas.

## 5. Alta y baja de empleados

Desde el enlace "Gestión de empleados" (visible en la pantalla de subida y en la de revisión):

El listado de empleados es **único para las tres empresas** — a diferencia de la pantalla de subida, aquí no hay que elegir ninguna empresa para ver la lista de personal. Esto es así porque una misma persona puede trabajar para más de una empresa del grupo con una sola ficha, y aparecerá emparejada automáticamente en las nóminas de cualquier empresa cuyo PDF incluya su DNI ese mes.

Encima de la tabla hay un buscador ("Buscar por nombre"): escribe parte del nombre y la lista se filtra al instante, sin recargar la página — muy útil ahora que la plantilla ronda los 35-40 empleados. No hace falta escribir las tildes ni respetar mayúsculas/minúsculas.

- **Dar de alta**: rellena nombre completo, DNI/NIE y email en el formulario, y pulsa "Dar de alta".
- **Editar**: pulsa "Editar" en la fila del empleado, cambia lo que haga falta y pulsa "Guardar cambios".
- **Dar de baja**: pulsa "Dar de baja" en la fila del empleado (te pedirá confirmación). Esto NO borra al empleado ni su historial — solo deja de aparecer en el listado por defecto y ya no se le podrán emparejar nóminas. Para volver a verlo, usa el enlace "Mostrar también los de baja".
- **Reactivar**: si un empleado dado de baja vuelve a la empresa (o se dio de baja por error), usa el enlace "Mostrar también los de baja" para verlo y pulsa "Reactivar" en su fila. Vuelve a quedar activo sin crear una ficha nueva ni tocar su historial de envíos anteriores.

## 6. Modo prueba / producción

En la raíz de la aplicación hay un archivo llamado **`config.local.py`** con dos valores:

```python
MODO_ENVIO = "prueba"
EMAIL_PRUEBA = "tu_email@dominio.com"
```

- **`"prueba"`**: todos los correos, sean de quien sean, llegan siempre a `EMAIL_PRUEBA` (tu propio email). Es el modo seguro para hacer pruebas sin riesgo de que le llegue una nómina a la persona equivocada. La propia pantalla de revisión muestra en todo momento un aviso indicando que estás en este modo.
- **`"produccion"`**: cada correo llega al email real de cada empleado, tal como está en su ficha.

Este documento no explica cómo ni cuándo cambiar a `"produccion"` — esa decisión se toma aparte, con calma, cuando estés listo.
