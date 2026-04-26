#!/usr/bin/env bash
set -euo pipefail

export PATH="/home/app/.local/bin:$PATH"

# If args are passed, run them (useful for pytest, shells, etc.)
if [ $# -gt 0 ]; then
  echo "[backend] exec: $*"
  exec "$@"
fi

APP="backend.api.main:app"
HOST="0.0.0.0"
PORT="${PORT:-8000}"
DEV="${DEV:-0}"

if [ "$DEV" = "1" ]; then
  echo "[backend] DEV=1 → starting uvicorn with --reload on ${HOST}:${PORT}"
  ARGS=(--host "$HOST" --port "$PORT" --reload --reload-dir backend)
  # Add frontend reload dir only if present
  if [ -d /app/frontend ]; then
    ARGS+=(--reload-dir frontend)
  fi
  exec python -m uvicorn "$APP" "${ARGS[@]}"
else
  echo "[backend] starting uvicorn on ${HOST}:${PORT}"
  # production-style run (you can tune workers)
  exec python -m uvicorn "$APP" --host "$HOST" --port "$PORT" --workers 4
fi
