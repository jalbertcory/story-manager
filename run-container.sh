#!/bin/bash
set -e

echo "--- Starting container setup ---"

PGDATA=/tmp/pgdata

# Initialise database cluster if it does not exist or is invalid
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  rm -rf "$PGDATA"/*
  install -d -m 0700 -o postgres -g postgres "$PGDATA"
  chown -R postgres:postgres "$PGDATA"
  su postgres -c "initdb -D $PGDATA" >/dev/null
fi

# Clean up any stale PID file
rm -f "$PGDATA/postmaster.pid"

# Start PostgreSQL
su postgres -c "pg_ctl -D $PGDATA -o \"-c listen_addresses='localhost' -c unix_socket_directories='/var/run/postgresql'\" -w start" >/dev/null

# Wait for PostgreSQL to be ready
echo "--- Starting PostgreSQL ---"
until su postgres -c "pg_isready -h localhost" >/dev/null 2>&1; do
  echo "Waiting for PostgreSQL..."
  sleep 1
done
echo "--- PostgreSQL started ---"

# Ensure the application database exists
echo "--- Ensuring database exists ---"
su postgres -c "psql -h localhost -tc \"SELECT 1 FROM pg_database WHERE datname='story_manager'\" | grep -q 1 || psql -h localhost -c \"CREATE DATABASE story_manager\"" >/dev/null
echo "--- Database ensured ---"

# Set DATABASE_URL and run migrations
echo "--- Running database migrations ---"
export DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/story_manager?client_encoding=utf8"
PYTHONPATH=/app alembic -c backend/alembic.ini upgrade head
echo "--- Database migrations complete ---"

# Start backend and frontend processes
echo "--- Starting backend and frontend processes ---"
PYTHONPATH=/app uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 &
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
