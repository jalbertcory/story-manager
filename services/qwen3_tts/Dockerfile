FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/jalbertcory/story-manager"
LABEL org.opencontainers.image.description="Story Manager adapter for Qwen3-TTS preset, cloned, designed, and LoRA voices"
LABEL org.opencontainers.image.licenses="Apache-2.0"

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/qwen3_tts/pyproject.toml services/qwen3_tts/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/__init__.py services/speaker_similarity.py services/tts_consistency.py /app/services/
COPY services/omnivoice/__init__.py services/omnivoice/audio_quality.py /app/services/omnivoice/
COPY services/qwen3_tts /app/services/qwen3_tts

ENV PATH="/app/.venv/bin:${PATH}"
ENV HF_HOME="/models"
ENV QWEN3_TTS_DEVICE="auto"
ENV QWEN3_VOICE_STORE="/models/voices"
ENV QWEN3_LORA_ROOT="/models/lora"

VOLUME ["/models"]
EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=4)"]

CMD ["uvicorn", "services.qwen3_tts.server:app", "--host", "0.0.0.0", "--port", "8003"]
