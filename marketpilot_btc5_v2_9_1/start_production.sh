#!/usr/bin/env bash
set -e
mkdir -p "${MARKETPILOT_DATA_DIR:-/tmp/marketpilot-data}"
python bot.py &
exec gunicorn --workers 1 --threads 4 --timeout 120 --bind "0.0.0.0:${PORT:-10000}" webapp:app
