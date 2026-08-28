#!/bin/bash
# Instala (o reinstala) el LaunchAgent que mantiene el servidor de nóminas
# MEDIFORM PLUS corriendo permanentemente en segundo plano, en localhost:8001,
# en vez de tener que arrancarlo a mano cada vez con Iniciar_App.command.
#
# Uso (desde el propio Mac donde se usa la app, con el venv ya creado):
#   ./scripts/instalar_launch_agent.sh
#
# Seguro de ejecutar más de una vez: si ya había un LaunchAgent instalado, lo
# desinstala primero y lo vuelve a crear con la ruta actual del proyecto.

set -e

RUTA_PROYECTO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.mediformplus.nominas"
PLANTILLA="$RUTA_PROYECTO/scripts/com.mediformplus.nominas.plist.example"
DESTINO="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -f "$PLANTILLA" ]; then
    echo "ERROR: no se encuentra la plantilla $PLANTILLA" >&2
    exit 1
fi

if [ ! -x "$RUTA_PROYECTO/venv/bin/python3" ]; then
    echo "ERROR: no existe $RUTA_PROYECTO/venv/bin/python3 — crea antes el entorno virtual:" >&2
    echo "  python3 -m venv venv && ./venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

mkdir -p "$RUTA_PROYECTO/logs"
mkdir -p "$HOME/Library/LaunchAgents"

if launchctl list | grep -q "$LABEL"; then
    echo "Ya había un LaunchAgent $LABEL cargado, lo desinstalo primero..."
    launchctl unload "$DESTINO" 2>/dev/null || true
fi

sed "s#__RUTA_PROYECTO__#$RUTA_PROYECTO#g" "$PLANTILLA" > "$DESTINO"

launchctl load -w "$DESTINO"

echo "LaunchAgent $LABEL instalado y cargado."
echo "Servidor arrancando en segundo plano en http://localhost:8001 (127.0.0.1, no accesible desde otros equipos de la red)."
echo "Logs en: $RUTA_PROYECTO/logs/launchagent.log y launchagent_error.log"
echo
echo "A partir de ahora, Iniciar_App.command solo necesita abrir el navegador:"
echo "el servidor se mantiene vivo aunque se cierre sesión o se reinicie el Mac."
