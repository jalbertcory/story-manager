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
