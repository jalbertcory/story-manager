#!/bin/bash
set -e

PGDATA=/tmp/pgdata

# Initialise database cluster if it does not exist
if [ ! -d "$PGDATA" ]; then
  install -d -o postgres -g postgres "$PGDATA"
  su postgres -c "initdb -D $PGDATA" >/dev/null
fi

# Start PostgreSQL
su postgres -c "pg_ctl -D $PGDATA -o \"-c listen_addresses='localhost'\" -w start" >/dev/null

# Ensure the application database exists
su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='story_manager'\" | grep -q 1 || psql -c \"CREATE DATABASE story_manager\"" >/dev/null

# Run migrations before starting the apps
alembic -c backend/alembic.ini upgrade head

# Start backend and frontend processes
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --app-dir backend &
BACKEND_PID=$!

npm --prefix frontend run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

# Ensure all processes are cleaned up, including PostgreSQL
trap "kill $BACKEND_PID $FRONTEND_PID; su postgres -c 'pg_ctl -D $PGDATA -m fast stop' >/dev/null" EXIT

wait -n $BACKEND_PID $FRONTEND_PID

