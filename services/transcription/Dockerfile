FROM ghcr.io/astral-sh/uv:0.11.8 AS uv

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

LABEL org.opencontainers.image.source="https://github.com/jalbertcory/story-manager"
LABEL org.opencontainers.image.description="Story Manager WhisperX word-timestamp service"
LABEL org.opencontainers.image.licenses="BSD-2-Clause"

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpython3.12 \
        python3 \
        python3-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/transcription/pyproject.toml services/transcription/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/__init__.py /app/services/__init__.py
COPY services/transcription /app/services/transcription

ENV PATH="/app/.venv/bin:${PATH}"
ENV HF_HOME="/models"
ENV WHISPER_MODEL_CACHE="/models"
ENV WHISPER_MODEL="large-v3"
ENV WHISPER_DEVICE="auto"
ENV WHISPER_COMPUTE_TYPE="auto"
ENV WHISPER_BATCH_SIZE="4"

VOLUME ["/models"]
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=4)"]

CMD ["uvicorn", "services.transcription.server:app", "--host", "0.0.0.0", "--port", "8002"]
