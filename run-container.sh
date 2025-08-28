#!/bin/bash
set -e

echo "--- Starting container setup ---"

PGDATA=/tmp/pgdata

# Initialise database cluster if it does not exist
if [ ! -d "$PGDATA" ]; then
  echo "--- Initializing database cluster ---"
  install -d -o postgres -g postgres "$PGDATA"
  su postgres -c "initdb -D $PGDATA"
  echo "--- Database cluster initialized ---"
fi

# Start PostgreSQL
echo "--- Starting PostgreSQL ---"
su postgres -c "pg_ctl -D $PGDATA -o \"-c listen_addresses='*'\" -w start"
echo "--- PostgreSQL started ---"

# Ensure the application database exists
echo "--- Ensuring database exists ---"
su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='story_manager'\" | grep -q 1 || psql -c \"CREATE DATABASE story_manager\""
echo "--- Database ensured ---"

# Run migrations before starting the apps
echo "--- Running database migrations ---"
alembic -c backend/alembic.ini upgrade head
echo "--- Database migrations complete ---"

# Start backend and frontend processes
echo "--- Starting backend and frontend processes ---"
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --app-dir backend &
BACKEND_PID=$!

npm --prefix frontend run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

echo "--- Backend and frontend started ---"
echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"

# Ensure all processes are cleaned up, including PostgreSQL
trap "echo '--- Shutting down processes ---'; kill $BACKEND_PID $FRONTEND_PID; su postgres -c 'pg_ctl -D $PGDATA -m fast stop'; echo '--- Processes shut down ---'" EXIT

wait -n $BACKEND_PID $FRONTEND_PID

echo "--- Container setup complete ---"
