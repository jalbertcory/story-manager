# syntax=docker/dockerfile:1

# Pinned tool and runtime images. Dependabot keeps these tags current.
FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

# ---------------------------------------------------------------------------
# Frontend build. Only the compiled dist/ directory reaches the final image, so
# Node.js and node_modules are not shipped.
# ---------------------------------------------------------------------------
FROM node:26-slim AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Python dependencies, installed exactly as locked in uv.lock. Only the
# manifest and lockfile are copied here so source edits do not invalidate this
# layer.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-trixie AS python-deps

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Runtime image.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-trixie

# The PostgreSQL major version is pinned on purpose: installs keep their data
# directory in a volume, and a newer major cannot open an older cluster without
# pg_upgrade. The Debian release is pinned too so a base-image rollover cannot
# change which PostgreSQL major is available. The packaged default cluster is
# not created; run-container.sh initialises its own data directory.
RUN mkdir -p /etc/postgresql-common/createcluster.d \
    && echo "create_main_cluster = false" > /etc/postgresql-common/createcluster.d/story-manager.conf \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17 ffmpeg gosu tini \
    && rm -rf /var/lib/apt/lists/*

# The application runs as this unprivileged user. run-container.sh remaps it to
# PUID/PGID at startup; PostgreSQL keeps running as the packaged postgres user.
RUN groupadd --gid 1000 storymanager \
    && useradd --uid 1000 --gid storymanager --create-home --home-dir /home/storymanager \
        --shell /usr/sbin/nologin storymanager \
    && mkdir -p /app/library /app/backups /app/logs \
    && chown storymanager:storymanager /app/library /app/backups /app/logs

ENV PATH="/opt/venv/bin:/usr/lib/postgresql/17/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    STORY_MANAGER_BACKUP_DIR=/app/backups

WORKDIR /app
COPY --from=python-deps /opt/venv /opt/venv
COPY backend backend
COPY --from=frontend /src/frontend/dist frontend/dist
COPY --chmod=0755 run-container.sh run-container.sh

EXPOSE 8000

# /health returns 503 until the database answers; migrations run before the
# server starts, so allow a generous start period for large upgrades.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8)"]

# tini reaps zombies and forwards SIGTERM to the entrypoint script, which stops
# uvicorn and then PostgreSQL cleanly.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./run-container.sh"]
