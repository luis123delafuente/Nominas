#!/bin/bash
# Doble clic para arrancar la app de nóminas MEDIFORM PLUS.
cd "$(dirname "$0")"

source venv/bin/activate

(sleep 2 && open "http://localhost:8000") &

./venv/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
