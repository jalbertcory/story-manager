# Story Manager

Story Manager is a self-hosted library manager for EPUBs and web novels. It gives you a web UI for uploading, organizing, editing, and updating books, plus a read-only reader API for e-readers and OPDS clients.

## Features

- Manage uploaded EPUBs and tracked web novels in one library.
- Download and refresh supported web novels with FanFicFare.
- Preserve existing chapters when source sites remove older content.
- Edit book metadata, covers, chapters, cleaning configs, and series information.
- Expose read-only `/reader/*` endpoints secured by per-device API keys.

## Stack

- Backend: FastAPI, SQLAlchemy, Alembic, APScheduler
- Database: PostgreSQL
- Frontend: React, Vite, TanStack Query
- Packaging: Docker, Docker Compose
- Tooling: `uv`, `pyenv`, `nvm`, npm, pytest, Vitest, Playwright

## Quick Start

The simplest deployment path is Docker Compose:

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`. Persistent data is stored under `./config`.

For more deployment details, see [docs/deployment.md](docs/deployment.md).

## Local Development

Install the project runtimes:

```bash
pyenv install
nvm install
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
cd frontend && npm ci && cd ..
```

Start PostgreSQL and run the app:

```bash
make ensure-db
make run-api
make run-ui
```

The development UI runs at `http://localhost:5173`; the API runs at `http://localhost:8000`.

Useful commands:

```bash
make migrate
make test
make test-migrations
make e2e
```

For setup notes and testing details, see [docs/development.md](docs/development.md).

## Reader API

Story Manager includes a read-only API for e-readers and OPDS clients. Create one reader key per device from `Utilities` -> `Reader API Keys` in the web UI.

See [docs/reader-api.md](docs/reader-api.md) for endpoint and authentication details.

## Security

The admin web UI and `/api/*` routes do not currently have built-in user login. Keep them on a private network, VPN, or behind a real authentication layer. The `/reader/*` routes are designed for read-only API-key access.

See [docs/reverse-proxy.md](docs/reverse-proxy.md) before exposing anything publicly.
