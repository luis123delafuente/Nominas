#!/bin/bash
# Doble clic para abrir la app de nóminas MEDIFORM PLUS.
cd "$(dirname "$0")"

if curl -s -o /dev/null "http://localhost:8001"; then
  # El servidor ya está corriendo (normalmente vía el LaunchAgent
  # com.mediformplus.nominas instalado con scripts/instalar_launch_agent.sh).
  open "http://localhost:8001"
else
  # Sin LaunchAgent instalado todavía: arrancarlo aquí como antes.
  source venv/bin/activate
  (sleep 2 && open "http://localhost:8001") &
  ./venv/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
fi
