.PHONY: run-ui run-backend fmt lint test

run-ui:
	cd frontend && npm run dev

run-backend:
	uvicorn backend.app.main:app --reload --app-dir backend

fmt:
        python3.12 -m black backend
        python3.12 -m flake8 backend
        cd frontend && npx prettier --write .

lint:
        python3.12 -m flake8 backend
        cd frontend && npm run lint

test:
        export PYTHONPATH=. && python3.12 -m pytest backend/tests
        cd frontend && npm test -- --run
