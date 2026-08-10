#!/bin/bash
set -e

echo "--- Starting container setup ---"

PGDATA=/tmp/pgdata

# Locate PostgreSQL binaries regardless of installed version
PG_BIN=$(dirname "$(find /usr/lib/postgresql -name "initdb" 2>/dev/null | sort -V | tail -1)")
if [ -z "$PG_BIN" ] || [ "$PG_BIN" = "." ]; then
  echo "ERROR: PostgreSQL binaries not found under /usr/lib/postgresql" >&2
  exit 1
fi
echo "--- Using PostgreSQL binaries at $PG_BIN ---"

# Initialise database cluster if it does not exist or is invalid
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  rm -rf "$PGDATA"/*
  install -d -m 0700 -o postgres -g postgres "$PGDATA"
  chown -R postgres:postgres "$PGDATA"
  su postgres -c "$PG_BIN/initdb -D $PGDATA" >/dev/null
fi

# Clean up any stale PID file
rm -f "$PGDATA/postmaster.pid"

# Start PostgreSQL
su postgres -c "$PG_BIN/pg_ctl -D $PGDATA -o \"-c listen_addresses='localhost' -c unix_socket_directories='/var/run/postgresql'\" -w start" >/dev/null

# Wait for PostgreSQL to be ready
echo "--- Starting PostgreSQL ---"
until su postgres -c "$PG_BIN/pg_isready -h localhost" >/dev/null 2>&1; do
  echo "Waiting for PostgreSQL..."
  sleep 1
done
echo "--- PostgreSQL started ---"

APP_PID=""
cleanup() {
  echo "--- Shutting down processes ---"
  if [ -n "$APP_PID" ]; then
    kill "$APP_PID" 2>/dev/null || true
  fi
  su postgres -c "$PG_BIN/pg_ctl -D $PGDATA -m fast stop" >/dev/null 2>&1 || true
  echo "--- Processes shut down ---"
}
trap cleanup EXIT

# Ensure the application database exists
echo "--- Ensuring database exists ---"
su postgres -c "$PG_BIN/psql -h localhost -tc \"SELECT 1 FROM pg_database WHERE datname='story_manager'\" | grep -q 1 || $PG_BIN/psql -h localhost -c \"CREATE DATABASE story_manager\"" >/dev/null
echo "--- Database ensured ---"

# Set DATABASE_URL before serving or running an offline recovery command.
export DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/story_manager?client_encoding=utf8"
MODE="${1:-serve}"

if [ "$MODE" = "verify" ]; then
  if [ -z "${2:-}" ]; then
    echo "Usage: ./run-container.sh verify /app/backups/<filename>" >&2
    exit 2
  fi
  PYTHONPATH=/app python -m backend.app.backup_cli verify "$2"
  exit
fi

if [ "$MODE" = "restore" ]; then
  if [ -z "${2:-}" ]; then
    echo "Usage: ./run-container.sh restore /app/backups/<filename> --confirm-replace" >&2
    exit 2
  fi
  ARCHIVE_PATH="$2"
  shift 2
  PYTHONPATH=/app python -m backend.app.backup_cli restore \
    "$ARCHIVE_PATH" \
    --library-path /app/library \
    --database-url "$DATABASE_URL" \
    "$@"
  echo "--- Upgrading restored database ---"
  PYTHONPATH=/app alembic -c backend/alembic.ini upgrade head
  echo "--- Restore complete ---"
  exit
fi

if [ "$MODE" != "serve" ]; then
  echo "Unknown mode: $MODE (expected serve, verify, or restore)" >&2
  exit 2
fi

# Run migrations for the normal application startup path.
echo "--- Running database migrations ---"
PYTHONPATH=/app alembic -c backend/alembic.ini upgrade head
echo "--- Database migrations complete ---"

# APScheduler and the in-process queues require exactly one application process.
# This is an application invariant, not a deployment setting.
echo "--- Starting application (workers=1) ---"
PYTHONPATH=/app uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1 &
APP_PID=$!

echo "--- Application started (PID: $APP_PID) ---"

wait

echo "--- Container setup complete ---"
