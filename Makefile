.PHONY: run-ui run-backend fmt lint test

run-ui:
	cd frontend && npm run dev

run-backend:
	uvicorn backend.app.main:app --reload --app-dir backend

fmt:
	python3.13 -m black backend
	python3.13 -m flake8 backend
	cd frontend && npx prettier --write .

lint:
	python3.13 -m flake8 backend
	cd frontend && npm run lint

test:
	$(MAKE) test-container
	export PYTHONPATH=. && python3.13 -m pytest backend/tests
	cd frontend && npm test -- --run

.PHONY: test-container
test-container:
	docker build -t story-manager-test .
	docker run --rm -d --name story-manager-test-container story-manager-test
	sleep 5
	@if ! docker ps -f name=story-manager-test-container -q; then \
		echo "Container failed to start"; \
		docker logs story-manager-test-container; \
		docker stop story-manager-test-container; \
		exit 1; \
	fi
	docker stop story-manager-test-container > /dev/null
