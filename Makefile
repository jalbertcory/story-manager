.PHONY: run-ui run-backend fmt lint test

run-ui:
	cd frontend && npm run dev

run-backend:
	uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

start-db-container:
	docker run -d \
	  --name story-manager-db \
	  -e POSTGRES_DB=story_manager \
	  -e POSTGRES_USER=storyuser \
	  -e POSTGRES_PASSWORD=storypass \
	  -p 5432:5432 \
	  postgres:15

fmt:
	python3.13 -m black backend
	python3.13 -m flake8 backend
	cd frontend && npx prettier --write .

lint:
	python3.13 -m flake8 backend
	cd frontend && npm run lint

test:
	export PYTHONPATH=. && python3.13 -m pytest backend/tests
	cd frontend && npm test -- --run