# Copia este archivo a config.local.py (que no se sube a git) y ajusta los valores.
#
# MODO_ENVIO controla a quién van los correos de verdad:
#   - "prueba"      -> todos los correos se redirigen a EMAIL_PRUEBA, sin excepción.
#   - "produccion"  -> los correos van al email real de cada empleado.
#
# Si config.local.py no existe, o MODO_ENVIO no es uno de estos dos valores,
# el sistema arranca en modo "prueba" por seguridad (nunca en "produccion" por omisión).
MODO_ENVIO = "prueba"

# Tu email real, usado como destinatario de todos los envíos mientras MODO_ENVIO sea "prueba".
EMAIL_PRUEBA = "mi_email_real@dominio.com"
