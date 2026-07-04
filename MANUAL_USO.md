# Manual de uso — Nóminas MEDIFORM PLUS

Guía rápida del proceso mensual. No hace falta saber programar para seguirla.

## 1. Guarda el PDF de la gestoría

Cuando la gestoría te envíe el PDF mensual con todas las nóminas juntas, guárdalo en tu ordenador (en cualquier carpeta, no importa dónde). No hace falta que le cambies el nombre, pero si lo llamas de forma parecida a `NOMINAS_062026.pdf` (mes y año seguidos), la aplicación intentará adivinar el mes por ti en el siguiente paso.

## 2. Abre la aplicación

Haz doble clic en **`Iniciar_App.command`**. Se abrirá una ventana de terminal (no la cierres mientras uses la app) y, a los pocos segundos, se abrirá tu navegador automáticamente en la pantalla de subida.

Si el navegador no se abre solo, entra tú a mano en: `http://localhost:8000`

Para cerrar la aplicación cuando termines, cierra la ventana de terminal que se abrió (o pulsa Ctrl+C dentro de ella).

**Nota:** la primera vez que ejecutes `Iniciar_App.command` en un ordenador, macOS mostrará un aviso pidiendo permiso para controlar Mail.app. Hay que aceptarlo — si no, el envío de correos no funcionará. Solo lo pide esa primera vez.

## 3. Sube el PDF y confirma el mes

En la pantalla inicial:
1. Elige el archivo PDF de la gestoría.
2. Comprueba el campo "Mes de la nómina" — puede que ya se haya rellenado solo. Si no es correcto, corrígelo a mano (formato AAAA-MM, por ejemplo `2026-06` para junio de 2026).
3. Pulsa "Subir y analizar".

## 4. La pantalla de revisión: qué significa cada color

La aplicación separa el PDF en una nómina por trabajador e intenta emparejar cada una con la ficha de un empleado. Cada fila de la tabla sale con un color:

- 🟢 **Verde (DNI exacto)** — el DNI de la nómina coincide exactamente con el de un empleado dado de alta. Está autoconfirmada; no tienes que hacer nada salvo que quieras excluirla (desmarcando su casilla).
- 🟡 **Ámbar (revisar a mano)** — hay algo que no cuadra del todo y necesita que lo mires tú antes de aprobarla:
  - *"DNI coincide pero el nombre no cuadra"*: el DNI de la nómina es el de un empleado concreto, pero el nombre que trae el PDF no se parece al de su ficha. Puede ser un error de tecleo en la ficha o un problema al leer el PDF. Compara los dos nombres que se muestran y, si de verdad es la misma persona, marca la casilla para incluirla; si no, corrige antes la ficha del empleado.
  - *"Coincidencia por nombre (sin DNI en la nómina)"*: esa nómina en concreto no traía un DNI legible, así que el emparejamiento se ha hecho solo por el nombre. Revisa que sea la persona correcta antes de marcar la casilla.
- 🔴 **Rojo (sin match)** — no se ha encontrado ningún empleado que corresponda a esa nómina. No se puede enviar hasta que lo arregles: normalmente porque el empleado todavía no está dado de alta (ve a "Gestión de empleados" y date de alta), o porque el DNI de su ficha tiene una errata.

Puedes pulsar "Ver" en cualquier fila para previsualizar el PDF de esa nómina (sin cifrar) antes de decidir.

Cuando estés conforme, pulsa **"Enviar"**. La aplicación cifra cada PDF confirmado con el DNI del trabajador como contraseña y lo envía por correo desde Mail.app. Al final verás un resumen de qué se envió y a quién (o el motivo si algo falló).

El correo sale siempre desde la cuenta que Mail.app tenga marcada como predeterminada en ese ordenador (Mail → Ajustes → Redacción). Si cambias esa cuenta predeterminada, cambiará también el remitente de las nóminas.

## 5. Alta y baja de empleados

Desde el enlace "Gestión de empleados" (visible en la pantalla de subida y en la de revisión):

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
