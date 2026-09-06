# Development

This project uses Python 3.13.5, Node.js 22, PostgreSQL, `uv`, `pyenv`, and `nvm`.

## First-Time Setup

```bash
git clone https://github.com/jalbertcory/story-manager.git
cd story-manager

pyenv install
nvm install

uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

cd frontend
npm ci
cd ..
```

Create a root `.env` file for the local database:

```text
DATABASE_URL=postgresql+psycopg://storyuser:storypass@localhost:5432/story_manager
```

## Running Locally

After first-time setup, start every local service with one command:

```bash
make start
```

The command starts only missing services: PostgreSQL, Ollama, the API, the UI,
OmniVoice, Qwen3-TTS, and WhisperX. It waits for health checks, leaves healthy existing
processes alone, and runs detached services with logs under `.run/logs/`.
Check their current state at any time with `make services-status`.

The development UI runs at `http://localhost:5173`; the API runs at
`http://localhost:8000`. The first OmniVoice, Qwen3-TTS, and WhisperX setups can take
several minutes. WhisperX stores downloaded models under
`.run/models/whisperx`. If the recommended Ollama model is missing, install it
with `make pull-ollama-model`.

### Start services individually

Start or create the local PostgreSQL container:

```bash
make ensure-db
```

Run migrations:

```bash
make migrate
```

Start the backend:

```bash
make run-api
```

Start the frontend in a separate terminal:

```bash
make run-ui
```

Local URLs:

- Web UI: `http://localhost:5173`
- API: `http://localhost:8000`
- Health check: `http://localhost:8000/health`

## Optional audio services

`make run-omnivoice` installs and runs the optional official local OmniVoice adapter for real audiobook speech.
See [services/omnivoice/README.md](../services/omnivoice/README.md) for hardware notes and configuration.

`make run-qwen3-tts` runs the optional Qwen3-TTS adapter on port 8003. It supports built-in preset voices,
persistent designed/cloned voices, cross-cast voice-separation checks, and local PEFT LoRA adapters. See
[services/qwen3_tts/README.md](../services/qwen3_tts/README.md) for voice IDs and configuration.

`make run-transcription` installs and runs the local WhisperX word-timestamp
service. See
[services/transcription/README.md](../services/transcription/README.md) for model
and hardware configuration.

## Stack

- Backend: FastAPI, SQLAlchemy, Alembic, APScheduler
- Database: PostgreSQL
- Frontend: React, Vite, TanStack Query
- Packaging: Docker, Docker Compose
- Tooling: `uv`, `pyenv`, `nvm`, npm, pytest, Vitest, Playwright

## Database

Local development uses PostgreSQL in Docker:

- Username: `storyuser`
- Password: `storypass`
- Database: `story_manager`
- Port: `5432`

Connect with:

```bash
psql -h localhost -p 5432 -U storyuser -d story_manager
```

Use Alembic migrations for database changes. Do not put one-time schema or data changes in application startup code.

## Tests

Run the checks required before publishing a PR:

```bash
make pr-check
```

This runs Python formatting/linting, Python type checking, frontend linting,
and frontend dependency audits. CI also audits Python dependencies.

Run Python type checking on its own:

```bash
make typecheck
```

Mypy runs in strict mode across all application modules in `backend/app` and all
production Python under `services`. Functions need complete signatures, collections
need type arguments, and typed functions cannot silently return `Any` or call
untyped functions. Strict mode also checks incompatible comparisons and requires
explicit public re-exports.
It targets Python 3.13, matching the development and CI environment. Test fixtures,
Alembic migration scripts, and operational scripts are outside this gate.
New application/service modules are included automatically.

The pinned checker and third-party stubs are installed with the root `dev` extra.
Optional model runtimes remain in their isolated environments; narrow import
exceptions in `pyproject.toml` cover those packages and upstream libraries without
typing metadata. Their APIs are not fully checked, but our adapter code is.
Keep exceptions limited to the external library; do not exclude application modules
or add broad error suppressions. Use precise schemas, `TypedDict`, protocols, and
explicit handling of nullable values when fixing errors. Dynamic JSON and untyped
external libraries still require narrow validation or documented casts at their
boundaries; strict mode does not mean every external value is statically known.

Run backend and frontend unit tests:

```bash
make test
```

Run migrations against a throwaway PostgreSQL container:

```bash
make test-migrations
```

Run Playwright E2E tests:

```bash
make e2e
```

Debug Playwright tests:

```bash
make e2e-debug
```

For local E2E tests, the Makefile starts a throwaway PostgreSQL container on port `5434`. Playwright starts dedicated backend and frontend dev servers on ports `18000` and `15173` unless `CI` is set.
