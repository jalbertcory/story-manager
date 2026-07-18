FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/jalbertcory/story-manager"
LABEL org.opencontainers.image.description="Story Manager adapter for the official k2-fsa/OmniVoice model"
LABEL org.opencontainers.image.licenses="Apache-2.0"

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/omnivoice/pyproject.toml services/omnivoice/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/omnivoice /app/services/omnivoice

ENV PATH="/app/.venv/bin:${PATH}"
ENV HF_HOME="/models"
ENV OMNIVOICE_DEVICE="auto"
ENV OMNIVOICE_NUM_STEPS="16"
ENV OMNIVOICE_MP3_BITRATE="96k"

VOLUME ["/models"]
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4)"]

CMD ["uvicorn", "services.omnivoice.server:app", "--host", "0.0.0.0", "--port", "8001"]
