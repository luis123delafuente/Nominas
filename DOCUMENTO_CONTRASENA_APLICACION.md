# Cómo generar la "contraseña de aplicación" para el envío de nóminas

Este documento es para ti, que gestionas el email de la empresa — no hace falta ningún
conocimiento técnico para seguirlo.

## ¿Por qué hace falta esto?

El programa envía las nóminas usando tu cuenta de email real (Gmail o Outlook), igual
que si las mandaras tú a mano. Pero por seguridad, Gmail y Outlook **no permiten** que un
programa use tu contraseña normal de correo — piden en su lugar una "contraseña de
aplicación": una contraseña especial, distinta de la tuya, que solo sirve para que este
programa concreto pueda enviar correos desde tu cuenta.

Esta contraseña de aplicación:
- Se genera **una sola vez** por cuenta de email (no hay que repetirlo cada mes).
- Se puede revocar en cualquier momento desde la configuración de tu cuenta, sin afectar
  a tu contraseña normal ni a cómo entras tú a leer el correo.
- No sustituye a tu contraseña habitual — la sigues usando igual para entrar a Gmail o
  Outlook desde el navegador o el móvil.

Necesitas tener activada la **verificación en dos pasos** en tu cuenta antes de poder
generar una contraseña de aplicación. Si no la tienes activada, el primer paso de cada
sección de abajo te lleva a activarla.

---

## Opción A — Cuenta de Gmail

1. Entra en tu cuenta de Google desde el navegador: ve a **myaccount.google.com** y, si
   te lo pide, inicia sesión con tu email y tu contraseña normal.
2. En el menú de la izquierda, entra en **"Seguridad"**.
3. Busca el apartado **"Verificación en dos pasos"**. Si aparece como "Desactivada",
   pulsa encima y sigue los pasos para activarla (normalmente te pedirá confirmar con tu
   móvil). Si ya está activada, pasa al siguiente punto.
4. Con la verificación en dos pasos activada, en esa misma página de Seguridad busca
   **"Contraseñas de aplicaciones"** (a veces hay que buscarla escribiendo "contraseñas
   de aplicaciones" en el buscador de arriba de la página, dentro de "Mi cuenta de
   Google").
5. Te pedirá que **pongas un nombre** para identificarla — escribe algo como "Nóminas
   Mediform" para reconocerla luego.
6. Pulsa **"Crear"**. Google te mostrará una contraseña de **16 letras**, agrupadas en
   4 bloques de 4 (por ejemplo: `abcd efgh ijkl mnop`).
7. **Copia esa contraseña ahora mismo** (con o sin espacios, da igual) — Google solo la
   muestra una vez, no podrás volver a verla después. Si la pierdes, tendrás que crear
   una nueva repitiendo estos pasos.
8. Pásame (a tu desarrollador) esa contraseña junto con la dirección de Gmail que vas a
   usar para enviar las nóminas, para darla de alta en el programa. Una vez dada de
   alta, esta contraseña se guarda cifrada — ni siquiera queda visible en la base de
   datos del programa.

**Datos del servidor que necesitará el programa** (esto lo hace tu desarrollador, tú no
tienes que anotarlo): servidor `smtp.gmail.com`, puerto `587`.

---

## Opción B — Cuenta de Outlook / Office365

1. Entra en **myaccount.microsoft.com** o en **account.live.com/proofs/AppPassword**
   (según si es una cuenta personal de Outlook o una cuenta de empresa/Office365) e
   inicia sesión con tu email y tu contraseña normal.
2. Busca **"Seguridad"** o **"Opciones de seguridad avanzadas"**.
3. Busca **"Verificación en dos pasos"** (a veces aparece como "Autenticación en dos
   pasos" o "Verificación en dos fases"). Si está desactivada, actívala primero
   siguiendo las indicaciones en pantalla (normalmente confirmando con tu móvil).
4. Una vez activada, busca la opción **"Contraseñas de aplicación"** dentro de esa misma
   sección de seguridad.
5. Pulsa **"Crear una nueva contraseña de aplicación"**. Microsoft te dará un nombre para
   ella o te dejará escribir uno — puedes poner "Nóminas Mediform".
6. Te mostrará una contraseña generada automáticamente. **Cópiala ahora mismo**, antes
   de cerrar esa ventana — igual que con Gmail, después ya no se puede volver a ver.
7. Pásame (a tu desarrollador) esa contraseña junto con la dirección de Outlook/Office365
   que vas a usar para enviar las nóminas.

**Nota para cuentas de empresa (Office365 gestionado por un administrador):** si tu
cuenta la administra un departamento de IT o un administrador de Microsoft 365, puede
que la opción de "Contraseñas de aplicación" esté oculta o bloqueada por política de la
organización. En ese caso, pídele al administrador que:
- Active las "contraseñas de aplicación" para tu cuenta, o
- Te confirme que la autenticación SMTP básica está permitida para tu buzón (si no usa
  verificación en dos pasos).

**Datos del servidor que necesitará el programa**: servidor `smtp.office365.com`,
puerto `587`.

---

## Qué hacer si algo falla

- **"No encuentro la opción de contraseñas de aplicación"**: casi siempre es porque la
  verificación en dos pasos no está activada todavía — actívala primero, la opción
  aparece justo después.
- **"El programa da un error de usuario/contraseña al enviar"**: lo más habitual es
  haber copiado mal la contraseña de aplicación (con espacios de más, o un carácter
  cambiado) al dársela a tu desarrollador. Genera una nueva y vuelve a pasarla,
  no hace falta reutilizar la anterior.
- **"He cambiado mi contraseña normal de Gmail/Outlook"**: no afecta a la contraseña de
  aplicación, siguen siendo independientes. Solo tendrás que generar una nueva contraseña
  de aplicación si tú mismo la revocas o si la cuenta pide reautorizar el acceso.
