.PHONY: run-ui run-backend fmt lint test

run-ui:
	cd frontend && npm run dev

run-backend:
	uvicorn backend.app.main:app --reload --app-dir backend

fmt:
	python -m black backend
	cd frontend && npx prettier --write .

lint:
	flake8 backend
	cd frontend && npm run lint

test:
	pytest backend/tests
	cd frontend && npm test -- --run
