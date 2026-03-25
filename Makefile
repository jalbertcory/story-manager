.PHONY: run-ui run-backend run-db ensure-db fmt lint test test-migrations e2e e2e-debug

run-ui:
	cd frontend && npm run dev

run-api:
	export PYTHONPATH=backend && .venv/bin/alembic -c backend/alembic.ini upgrade head && \
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-db:
	docker run -d \
	  --name story-manager-db \
	  -e POSTGRES_DB=story_manager \
	  -e POSTGRES_USER=storyuser \
	  -e POSTGRES_PASSWORD=storypass \
	  -p 5432:5432 \
	  postgres:17

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
	$(MAKE) ensure-db
	cd frontend && npm run test:e2e

e2e-debug:
	$(MAKE) ensure-db
	cd frontend && npm run test:e2e:debug
