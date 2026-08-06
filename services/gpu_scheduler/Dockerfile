FROM ghcr.io/astral-sh/uv:0.11.8 AS uv

FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/jalbertcory/story-manager"
LABEL org.opencontainers.image.description="Story Manager scheduled GPU-container availability controller"
LABEL org.opencontainers.image.licenses="BSD-2-Clause"

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY services/gpu_scheduler/pyproject.toml services/gpu_scheduler/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/__init__.py /app/services/__init__.py
COPY services/gpu_scheduler /app/services/gpu_scheduler

ENV PATH="/app/.venv/bin:${PATH}"
ENV SCHEDULER_DATA_PATH="/data/config.json"
ENV SCHEDULER_RECONCILE_SECONDS="15"

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4)"]

CMD ["uvicorn", "services.gpu_scheduler.server:app", "--host", "0.0.0.0", "--port", "8765"]
