.PHONY: help start start-services services-status setup setup-omnivoice run-omnivoice setup-transcription run-transcription build-transcription-image pull-ollama-model run-gpu-scheduler managed-ai gpu-services-status test-gpu-scheduler run-ui run-api run-db ensure-db migrate fmt lint lint-backend lint-ui pr-check test test-migrations e2e e2e-debug

E2E_DB_CONTAINER ?= story-manager-e2e-db
E2E_DB_PORT ?= 5434
OMNIVOICE_PORT ?= 8001
TRANSCRIPTION_PORT ?= 8002
WHISPER_LANGUAGE ?= en
WHISPER_MODEL_CACHE ?= .run/models/whisperx
GPU_SCHEDULER_COMPOSE_FILE ?= services/gpu_scheduler/compose.windows.yaml
GPU_SCHEDULER_URL ?= http://127.0.0.1:8765
GPU_SCHEDULER_BUILD ?=
MANAGED_AI_SERVICES ?= ollama omnivoice transcription
GPU_COMPOSE = docker compose -f $(GPU_SCHEDULER_COMPOSE_FILE)

help:
	@echo "Story Manager commands:"
	@echo "  make start            Start all missing local services"
	@echo "  make services-status  Show local service health"
	@echo "  make setup            Install project dependencies"
	@echo "  make ensure-db        Create or start the local PostgreSQL container"
	@echo "  make migrate          Run Alembic migrations"
	@echo "  make run-api          Run the FastAPI backend"
	@echo "  make run-ui           Run the Vite frontend"
	@echo "  make setup-omnivoice  Install official OmniVoice in an isolated environment"
	@echo "  make run-omnivoice    Run the local MPS/CUDA/CPU OmniVoice adapter"
	@echo "  make run-transcription Run the local WhisperX timestamp service"
	@echo "  make build-transcription-image Build the production WhisperX image"
	@echo "  make pull-ollama-model Pull the recommended local audiobook LLM"
	@echo "  make run-gpu-scheduler Start the GPU availability control panel"
	@echo "  make managed-ai       Create model containers for control by the scheduler"
	@echo "  make gpu-services-status Show scheduler and managed-container state"
	@echo "  make test-gpu-scheduler Run scheduler unit tests"
	@echo "  make pr-check         Run the required pre-PR lint checks"
	@echo "  make test             Run backend and frontend unit tests"
	@echo "  make test-migrations  Run migrations against throwaway PostgreSQL"
	@echo "  make e2e              Run Playwright E2E tests"
	@echo "  make e2e-debug        Run Playwright E2E tests in debug mode"

start: start-services

start-services:
	./scripts/start-services.sh start

services-status:
	./scripts/start-services.sh status

setup:
	pyenv install -s
	uv venv
	uv pip install -e ".[dev]"
	cd frontend && npm ci

setup-omnivoice:
	uv sync --project services/omnivoice --python 3.13

run-omnivoice: setup-omnivoice
	PYTORCH_ENABLE_MPS_FALLBACK=1 services/omnivoice/.venv/bin/uvicorn \
		services.omnivoice.server:app --host 127.0.0.1 --port $(OMNIVOICE_PORT)

setup-transcription:
	uv sync --project services/transcription --python 3.13

run-transcription: setup-transcription
	mkdir -p $(WHISPER_MODEL_CACHE)
	WHISPER_LANGUAGE=$(WHISPER_LANGUAGE) \
		WHISPER_MODEL_CACHE=$(WHISPER_MODEL_CACHE) \
		services/transcription/.venv/bin/uvicorn \
		services.transcription.server:app --host 127.0.0.1 --port $(TRANSCRIPTION_PORT)

build-transcription-image:
	docker build --platform linux/amd64 \
		-f services/transcription/Dockerfile \
		-t story-manager-transcription:local .

pull-ollama-model:
	ollama pull qwen3.5:9b

run-gpu-scheduler:
	@if [ -z "$(GPU_SCHEDULER_BUILD)" ]; then \
		$(GPU_COMPOSE) pull gpu-scheduler; \
	fi
	$(GPU_COMPOSE) up -d $(GPU_SCHEDULER_BUILD) gpu-scheduler
	@until curl --silent --show-error --fail --max-time 3 $(GPU_SCHEDULER_URL)/health >/dev/null 2>&1; do \
		printf "."; \
		sleep 1; \
	done; \
	echo " GPU scheduler is ready at $(GPU_SCHEDULER_URL)."

managed-ai: run-gpu-scheduler
	$(GPU_COMPOSE) pull $(MANAGED_AI_SERVICES)
	$(GPU_COMPOSE) create $(MANAGED_AI_SERVICES)
	@curl --silent --show-error --fail \
		-X POST $(GPU_SCHEDULER_URL)/api/reconcile >/dev/null
	@echo "Managed AI containers are registered. Their desired state is controlled at $(GPU_SCHEDULER_URL)."

gpu-services-status:
	@$(GPU_COMPOSE) ps -a
	@printf '\nScheduler state:\n'
	@if command -v jq >/dev/null 2>&1; then \
		curl --silent --show-error --fail $(GPU_SCHEDULER_URL)/api/state | \
			jq '{policy_source, desired_available, containers, last_error}'; \
	else \
		curl --silent --show-error --fail $(GPU_SCHEDULER_URL)/api/state; \
		printf '\n'; \
	fi

test-gpu-scheduler:
	PYTHONPATH=. uv run --project services/gpu_scheduler pytest services/gpu_scheduler/tests

run-ui:
	cd frontend && npm run dev

run-api:
	$(MAKE) migrate
	STORY_MANAGER_PG_DUMP_CONTAINER=story-manager-db \
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

lint: lint-backend lint-ui

lint-backend:
	.venv/bin/python3 -m black --check backend
	.venv/bin/python3 -m autoflake --check --remove-all-unused-imports --recursive backend
	.venv/bin/python3 -m flake8 backend --count --statistics

lint-ui:
	cd frontend && npm run lint -- --max-warnings=0

pr-check: lint

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
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0016; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "INSERT INTO books (title, author, source_type) VALUES ('Migration Test', 'Story Manager', 'epub');" \
		-c "INSERT INTO book_metadata_matches (book_id, status) SELECT id, 'pending' FROM books WHERE title = 'Migration Test';"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "INSERT INTO book_metadata_matches (book_id, status) SELECT id, 'pending' FROM books WHERE title = 'Migration Test';"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0016; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "DO \$$\$$ BEGIN IF (SELECT COUNT(*) FROM book_metadata_matches) <> 1 THEN RAISE EXCEPTION 'downgrade did not preserve exactly one match'; END IF; END \$$\$$;"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0022; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "UPDATE books SET audiobook_enabled = true, audiobook_pipeline_status = 'complete', content_version = 3 WHERE title = 'Migration Test';" \
		-c "INSERT INTO audiobook_chapters (book_id, chapter_number, content_file_name, audio_file_path, smil_file_path, needs_reassembly) SELECT id, 1, 'Text/existing.xhtml', 'library/existing.mp3', 'library/existing.smil', false FROM books WHERE title = 'Migration Test';" \
		-c "INSERT INTO audiobook_sentences (chapter_id, html_element_id, sequence_order, original_text, audio_duration_ms, status) SELECT id, 'existing-sentence', 0, 'Existing sentence.', 1250, 'audio_generated' FROM audiobook_chapters WHERE content_file_name = 'Text/existing.xhtml';"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT 1 FROM audiobook_chapters WHERE stable_chapter_key IS NOT NULL AND generation_state = 'ready' AND audio_revision = 1 AND duration_ms = 1250) THEN RAISE EXCEPTION 'existing audiobook chapter was not backfilled'; END IF; IF NOT EXISTS (SELECT 1 FROM books WHERE title = 'Migration Test' AND audiobook_publication_state = 'complete' AND audiobook_text_content_version = 3) THEN RAISE EXCEPTION 'existing audiobook book metadata was not backfilled'; END IF; END \$$\$$;"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0022; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT 1 FROM audiobook_chapters WHERE content_file_name = 'Text/existing.xhtml') THEN RAISE EXCEPTION 'audiobook downgrade removed existing chapter'; END IF; END \$$\$$;"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0023; \
	docker exec -i story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		< scripts/migration-preexisting-audiobook-setup.sql; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT 1 FROM imported_audiobooks WHERE name = 'Pre-existing imported edition' AND derived_revision = 0 AND derived_format_version = 0) THEN RAISE EXCEPTION '0036 did not backfill imported audiobook revision metadata'; END IF; IF NOT EXISTS (SELECT 1 FROM imported_audiobook_tracks WHERE title = 'Existing chapter' AND source_audio_file_path = audio_file_path AND source_clip_begin_ms = source_start_ms AND source_clip_end_ms = source_end_ms) THEN RAISE EXCEPTION '0036 did not preserve immutable imported track coordinates'; END IF; END \$$\$$;"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0023; \
	docker exec -i story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		< scripts/migration-preexisting-audiobook-verify.sql; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade 0032; \
	docker exec -i story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		< scripts/migration-lifecycle-setup.sql; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	docker exec -i story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		< scripts/migration-lifecycle-verify.sql; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0032; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "UPDATE books SET refresh_status = 'constraint-removed' WHERE title = 'Migration Test';" \
		-c "INSERT INTO processing_jobs (job_type) VALUES ('clean_all');"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini upgrade head; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT 1 FROM processing_jobs WHERE request_id LIKE 'legacy-%') THEN RAISE EXCEPTION 'processing request id was not backfilled'; END IF; IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE tablename = 'processing_jobs' AND indexname = 'ix_processing_jobs_request_id') THEN RAISE EXCEPTION 'processing request id index was not created'; END IF; END \$$\$$;"; \
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
	PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini downgrade 0033; \
	docker exec story-manager-migration-test psql -v ON_ERROR_STOP=1 -U postgres -d story_manager \
		-c "DO \$$\$$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'processing_jobs' AND column_name = 'request_id') THEN RAISE EXCEPTION 'processing request id column survived downgrade'; END IF; END \$$\$$;"

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
