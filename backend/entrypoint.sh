#!/bin/bash
set -e

if [ "${RUN_MIGRATIONS:-true}" != "false" ]; then
  echo "Running migrations..."
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
