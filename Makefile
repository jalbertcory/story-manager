.PHONY: help setup run-ui run-api run-db ensure-db migrate fmt lint test test-migrations e2e e2e-debug

E2E_DB_CONTAINER ?= story-manager-e2e-db
E2E_DB_PORT ?= 5434

help:
	@echo "Story Manager commands:"
	@echo "  make setup            Install project dependencies"
	@echo "  make ensure-db        Create or start the local PostgreSQL container"
	@echo "  make migrate          Run Alembic migrations"
	@echo "  make run-api          Run the FastAPI backend"
	@echo "  make run-ui           Run the Vite frontend"
	@echo "  make test             Run backend and frontend unit tests"
	@echo "  make test-migrations  Run migrations against throwaway PostgreSQL"
	@echo "  make e2e              Run Playwright E2E tests"
	@echo "  make e2e-debug        Run Playwright E2E tests in debug mode"

setup:
	pyenv install -s
	uv venv
	uv pip install -e ".[dev]"
	cd frontend && npm ci

run-ui:
	cd frontend && npm run dev

run-api:
	$(MAKE) migrate
	PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-db: ensure-db

ensure-db:
	@if docker ps --format '{{.Names}}' | grep -qx 'story-manager-db'; then \
		echo "Postgres is already running."; \
	elif docker ps -a --format '{{.Names}}' | grep -qx 'story-manager-db'; then \
		echo "Starting existing Postgres container..."; \
		docker start story-manager-db >/dev/null; \
	else \
		echo "Creating Postgres container..."; \
		docker run -d \
		  --name story-manager-db \
		  -e POSTGRES_DB=story_manager \
		  -e POSTGRES_USER=storyuser \
		  -e POSTGRES_PASSWORD=storypass \
		  -p 5432:5432 \
		  postgres:17 >/dev/null; \
	fi
	@until docker exec story-manager-db pg_isready -U storyuser -d story_manager >/dev/null 2>&1; do \
		printf "."; \
		sleep 1; \
	done; \
	echo " Postgres is ready."

migrate:
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head

fmt:
	.venv/bin/python3 -m black backend
	.venv/bin/python3 -m flake8 backend
	cd frontend && npx prettier --write .

lint:
	.venv/bin/python3 -m flake8 backend
	cd frontend && npm run lint

test:
	export PYTHONPATH=. && .venv/bin/python3 -m pytest -m "not integration" backend/tests
	cd frontend && npm test -- --run

test-migrations:
	docker rm -f story-manager-migration-test >/dev/null 2>&1 || true
	docker run --name story-manager-migration-test \
	  -e POSTGRES_PASSWORD=postgres \
	  -e POSTGRES_DB=story_manager \
	  -p 5433:5432 \
	  -d postgres:17 >/dev/null
	@trap 'docker rm -f story-manager-migration-test >/dev/null 2>&1 || true' EXIT; \
	until docker exec story-manager-migration-test pg_isready -U postgres -d story_manager >/dev/null 2>&1; do \
		printf "."; \
		sleep 1; \
	done; \
	echo " Postgres is ready."; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head

e2e:
	docker rm -f $(E2E_DB_CONTAINER) >/dev/null 2>&1 || true
	docker run --name $(E2E_DB_CONTAINER) \
	  -e POSTGRES_PASSWORD=postgres \
	  -e POSTGRES_DB=story_manager \
	  -p $(E2E_DB_PORT):5432 \
	  -d postgres:17 >/dev/null
	@trap 'docker rm -f $(E2E_DB_CONTAINER) >/dev/null 2>&1 || true' EXIT; \
	until docker exec $(E2E_DB_CONTAINER) pg_isready -U postgres -d story_manager >/dev/null 2>&1; do \
		printf "."; \
		sleep 1; \
	done; \
	echo " E2E Postgres is ready."; \
	export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:$(E2E_DB_PORT)/story_manager"; \
	cd frontend && npm run test:e2e

e2e-debug:
	docker rm -f $(E2E_DB_CONTAINER) >/dev/null 2>&1 || true
	docker run --name $(E2E_DB_CONTAINER) \
	  -e POSTGRES_PASSWORD=postgres \
	  -e POSTGRES_DB=story_manager \
	  -p $(E2E_DB_PORT):5432 \
	  -d postgres:17 >/dev/null
	@trap 'docker rm -f $(E2E_DB_CONTAINER) >/dev/null 2>&1 || true' EXIT; \
	until docker exec $(E2E_DB_CONTAINER) pg_isready -U postgres -d story_manager >/dev/null 2>&1; do \
		printf "."; \
		sleep 1; \
	done; \
	echo " E2E Postgres is ready."; \
	export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:$(E2E_DB_PORT)/story_manager"; \
	cd frontend && npm run test:e2e:debug
