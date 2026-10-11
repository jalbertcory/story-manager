ARG BASE_IMAGE=ghcr.io/jalbertcory/story-manager/base:cc2cd4089d5b76aec320b4de863c9f4dcdadc87e88ef9a74fc9a8260c8fa1c66
FROM ${BASE_IMAGE}

COPY pyproject.toml uv.lock ./
COPY backend backend
COPY frontend frontend
COPY run-container.sh run-container.sh

RUN chmod +x run-container.sh

RUN rm -f /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv export --quiet --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/requirements.txt \
    && /root/.local/bin/uv pip install --system --no-cache -r /tmp/requirements.txt \
    && /root/.local/bin/uv pip install --system --no-cache --no-deps .

RUN python -m spacy download en_core_web_sm

RUN npm --prefix frontend ci && npm --prefix frontend run build

EXPOSE 8000

CMD ["./run-container.sh"]
