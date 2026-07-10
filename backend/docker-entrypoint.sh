#!/bin/sh
# Applies Alembic migrations before serving, so `docker compose up` is a
# self-contained "just works" demo path — matches the container-startup
# convenience CI's separate explicit `alembic upgrade head` step doesn't
# need (CI runs against an already-migrated-once dev DB per its own
# comments), but this is the first time this project runs the backend
# inside a container, so nothing has migrated the DB it points at yet.
set -e

cd /app/backend
alembic upgrade head

cd /app/backend/app
exec uvicorn main:app --host 0.0.0.0 --port 8000
