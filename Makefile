.PHONY: run-ui run-backend fmt lint test

run-ui:
	cd frontend && npm run dev

run-backend:
	uvicorn backend.app.main:app --reload --app-dir backend

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
