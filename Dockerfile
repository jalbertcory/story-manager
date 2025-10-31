ARG BASE_IMAGE=ghcr.io/jules-dot-dev/story-manager-base:latest
FROM ${BASE_IMAGE}

COPY pyproject.toml .
COPY backend backend
COPY frontend frontend
COPY run-container.sh run-container.sh

RUN chmod +x run-container.sh

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv pip install --system --no-cache .

RUN npm --prefix frontend ci

EXPOSE 8000 5173

CMD ["./run-container.sh"]
