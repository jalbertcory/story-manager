#!/bin/bash
set -euo pipefail

echo "--- Starting container setup ---"

PGDATA="${PGDATA:-/tmp/pgdata}"
APP_USER=storymanager
# Directories the application writes to. Everything else in /app is read-only code.
APP_WRITABLE_DIRS=(/app/library /app/backups /app/logs)
# Overridden backup or log locations must be writable too (see backend/app/config.py).
for dir in "${STORY_MANAGER_BACKUP_DIR:-}" "${STORY_MANAGER_LOG_DIR:-}"; do
  if [ -n "$dir" ]; then
    APP_WRITABLE_DIRS+=("$dir")
  fi
done

EMBEDDED_POSTGRES=false
PG_BIN=""
APP_PID=""
# Command prefix that drops privileges to the application user (empty when the
# container already runs unprivileged). Used as a prefix rather than a function
# so a backgrounded application is exec'd directly and $! is its real PID.
AS_APP=()

stop_postgres() {
  if [ "$EMBEDDED_POSTGRES" = true ] && [ -f "$PGDATA/postmaster.pid" ]; then
    echo "--- Stopping PostgreSQL ---"
    gosu postgres "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true
  fi
}

# Runs on every exit path, including `docker stop` (SIGTERM via tini): stop the
# application first so it can finish in-flight work, then shut PostgreSQL down
# cleanly so the next start does not need crash recovery.
cleanup() {
  local status=$?
  trap - EXIT TERM INT
  echo "--- Shutting down processes ---"
  if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
    kill -TERM "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  stop_postgres
  echo "--- Processes shut down ---"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# Without PUID/PGID, keep whatever non-root owner an existing library already
# has (Unraid uses 99:100; rootless Docker and Podman map IDs differently), so an
# upgrade never re-owns it. Only a new or root-owned library falls back to 1000.
resolve_app_ids() {
  local owner_uid=0 owner_gid=0
  if [ -d /app/library ]; then
    owner_uid=$(stat -c %u /app/library)
    owner_gid=$(stat -c %g /app/library)
  fi
  if [ -z "${PUID:-}" ]; then
    if [ "$owner_uid" != "0" ]; then PUID=$owner_uid; else PUID=1000; fi
  fi
  if [ -z "${PGID:-}" ]; then
    if [ "$owner_uid" != "0" ]; then PGID=$owner_gid; else PGID=1000; fi
  fi
}

# FanFicFare reads personal.ini as the application user, and /app/config is
# usually mounted read-only, so ownership cannot be fixed here; say so instead.
warn_unreadable_fanficfare_config() {
  local ini="${FFF_USER_CONFIG_PATH:-/app/config/personal.ini}"
  if [ -f "$ini" ] && ! "${AS_APP[@]}" test -r "$ini"; then
    echo "WARNING: $ini is not readable by UID $PUID / GID $PGID; FanFicFare will ignore it." >&2
    echo "Make it readable (for example chmod a+r) or set PUID/PGID to its owner." >&2
  fi
}

prepare_app_user() {
  if [ "$(id -u)" -ne 0 ]; then
    return
  fi
  resolve_app_ids
  if [ "$PUID" = "0" ]; then
    echo "--- PUID=0: running the application as root ---"
    return
  fi
  AS_APP=(gosu "$APP_USER")
  if [ "$(id -g "$APP_USER")" != "$PGID" ]; then
    groupmod -o -g "$PGID" "$APP_USER"
  fi
  if [ "$(id -u "$APP_USER")" != "$PUID" ]; then
    usermod -o -u "$PUID" "$APP_USER"
  fi
  local dir
  for dir in "${APP_WRITABLE_DIRS[@]}" "$(getent passwd "$APP_USER" | cut -d: -f6)"; do
    mkdir -p "$dir"
    # Older images ran the application as root, so existing volumes may hold
    # root-owned files. Only touch entries that are not already owned correctly.
    if ! find "$dir" \( ! -user "$PUID" -o ! -group "$PGID" \) -exec chown -h "$PUID:$PGID" {} + 2>/dev/null; then
      echo "WARNING: could not change ownership of $dir to $PUID:$PGID; the application may be unable to write to it." >&2
    fi
  done
  echo "--- Application will run as UID $PUID / GID $PGID ---"
  warn_unreadable_fanficfare_config
}

start_embedded_postgres() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: the embedded PostgreSQL server needs the container to start as root." >&2
    echo "Start the container without a 'user:' override, or set DATABASE_URL to an external PostgreSQL server." >&2
    exit 1
  fi

  # Locate PostgreSQL binaries regardless of installed version
  PG_BIN=$(dirname "$(find /usr/lib/postgresql -name "initdb" 2>/dev/null | sort -V | tail -1)")
  if [ -z "$PG_BIN" ] || [ "$PG_BIN" = "." ]; then
    echo "ERROR: PostgreSQL binaries not found under /usr/lib/postgresql" >&2
    exit 1
  fi
  echo "--- Using PostgreSQL binaries at $PG_BIN ---"

  mkdir -p "$PGDATA"

  # A volume that is a filesystem root holds lost+found, and initdb refuses to
  # use a mount point directly. Keep the cluster in a subdirectory instead.
  if [ ! -f "$PGDATA/PG_VERSION" ] && { [ -f "$PGDATA/pgdata/PG_VERSION" ] || [ "$(ls -A "$PGDATA")" = "lost+found" ]; }; then
    chown postgres:postgres "$PGDATA"
    chmod 0700 "$PGDATA"
    PGDATA="$PGDATA/pgdata"
    echo "--- $(dirname "$PGDATA") is a mount point; using $PGDATA for the database ---"
    mkdir -p "$PGDATA"
  fi

  # Only initialise a brand-new, empty data directory. A non-empty directory
  # without PG_VERSION is most likely a mis-mapped volume (for example the
  # library folder); never delete or re-own its contents.
  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    if [ -n "$(ls -A "$PGDATA")" ]; then
      echo "ERROR: $PGDATA is not empty but does not contain a PostgreSQL cluster (no PG_VERSION file)." >&2
      echo "Check the volume mapped to $PGDATA. Refusing to initialise over existing files." >&2
      echo "Point it at an existing PostgreSQL data directory, or at an empty folder to create a new database." >&2
      exit 1
    fi
    chown postgres:postgres "$PGDATA"
    chmod 0700 "$PGDATA"
    echo "--- Initialising new PostgreSQL cluster in $PGDATA ---"
    gosu postgres "$PG_BIN/initdb" -D "$PGDATA" >/dev/null
  fi

  # The postgres UID can differ between image builds; PostgreSQL refuses to
  # start on a data directory it does not own.
  find "$PGDATA" \( ! -user postgres -o ! -group postgres \) -exec chown -h postgres:postgres {} +
  chmod 0700 "$PGDATA"
  install -d -m 2775 -o postgres -g postgres /var/run/postgresql

  # A stale PID file is left behind when the previous container was killed.
  # Nothing else can be running against this volume inside a fresh container.
  rm -f "$PGDATA/postmaster.pid"

  echo "--- Starting PostgreSQL ---"
  EMBEDDED_POSTGRES=true
  gosu postgres "$PG_BIN/pg_ctl" -D "$PGDATA" \
    -o "-c listen_addresses='localhost' -c unix_socket_directories='/var/run/postgresql'" \
    -w start >/dev/null
  until gosu postgres "$PG_BIN/pg_isready" -h localhost >/dev/null 2>&1; do
    echo "Waiting for PostgreSQL..."
    sleep 1
  done
  echo "--- PostgreSQL started ---"

  echo "--- Ensuring database exists ---"
  local exists
  exists=$(gosu postgres "$PG_BIN/psql" -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='story_manager'")
  if [ "$exists" != "1" ]; then
    gosu postgres "$PG_BIN/psql" -h localhost -c "CREATE DATABASE story_manager" >/dev/null
  fi
  echo "--- Database ensured ---"

  export DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/story_manager?client_encoding=utf8"
}

prepare_app_user

# A user-supplied DATABASE_URL points at an external PostgreSQL server; the
# embedded server is only started when none is configured.
if [ -n "${DATABASE_URL:-}" ]; then
  echo "--- Using external database from DATABASE_URL; embedded PostgreSQL is not started ---"
else
  start_embedded_postgres
fi

MODE="${1:-serve}"

if [ "$MODE" = "verify" ]; then
  if [ -z "${2:-}" ]; then
    echo "Usage: ./run-container.sh verify /app/backups/<filename>" >&2
    exit 2
  fi
  "${AS_APP[@]}" python -m backend.app.backup_cli verify "$2"
  exit
fi

if [ "$MODE" = "restore" ]; then
  if [ -z "${2:-}" ]; then
    echo "Usage: ./run-container.sh restore /app/backups/<filename> --confirm-replace" >&2
    exit 2
  fi
  ARCHIVE_PATH="$2"
  shift 2
  "${AS_APP[@]}" python -m backend.app.backup_cli restore \
    "$ARCHIVE_PATH" \
    --library-path /app/library \
    --database-url "$DATABASE_URL" \
    "$@"
  echo "--- Upgrading restored database ---"
  "${AS_APP[@]}" alembic -c backend/alembic.ini upgrade head
  echo "--- Restore complete ---"
  exit
fi

if [ "$MODE" != "serve" ]; then
  echo "Unknown mode: $MODE (expected serve, verify, or restore)" >&2
  exit 2
fi

# Run migrations for the normal application startup path.
echo "--- Running database migrations ---"
"${AS_APP[@]}" alembic -c backend/alembic.ini upgrade head
echo "--- Database migrations complete ---"

# APScheduler and the in-process queues require exactly one application process.
# This is an application invariant, not a deployment setting.
echo "--- Starting application (workers=1) ---"
# The graceful timeout stays under Docker's default 10-second stop timeout so a
# plain `docker stop` still leaves time to shut PostgreSQL down cleanly.
"${AS_APP[@]}" uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --timeout-graceful-shutdown 8 &
APP_PID=$!
echo "--- Application started (PID: $APP_PID) ---"

# `wait` returns early when TERM/INT arrives, which runs the cleanup trap.
wait "$APP_PID"
