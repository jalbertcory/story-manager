.PHONY: run-ui run-backend fmt lint test

run-ui:
	cd frontend && npm run dev

run-api:
	cd backend && export PYTHONPATH=. && ../.venv/bin/alembic upgrade head && \
	../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-db:
	docker run -d \
	  --name story-manager-db \
	  -e POSTGRES_DB=story_manager \
	  -e POSTGRES_USER=storyuser \
	  -e POSTGRES_PASSWORD=storypass \
	  -p 5432:5432 \
	  postgres:17

fmt:
	.venv/bin/python3 -m black backend
	.venv/bin/python3 -m flake8 backend
	cd frontend && npx prettier --write .

lint:
	.venv/bin/python3 -m flake8 backend
	cd frontend && npm run lint

test:
	export PYTHONPATH=. && .venv/bin/python3 -m pytest backend/tests
	cd frontend && npm test -- --run

e2e:
	cd frontend && npm run test:e2e

e2e-debug:
	cd frontend && npm run test:e2e:debug
