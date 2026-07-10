ARG BASE_IMAGE=ghcr.io/jalbertcory/story-manager/base:d9cc9830314ba91abb46c1350b942b7dbc5317a9d288707b7b2c16323a2a3b24
FROM ${BASE_IMAGE}

COPY pyproject.toml uv.lock ./
COPY backend backend
COPY frontend frontend
COPY run-container.sh run-container.sh

RUN chmod +x run-container.sh

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv export --quiet --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/requirements.txt \
    && /root/.local/bin/uv pip install --system --no-cache -r /tmp/requirements.txt \
    && /root/.local/bin/uv pip install --system --no-cache --no-deps .

RUN npm --prefix frontend ci && npm --prefix frontend run build

EXPOSE 8000

CMD ["./run-container.sh"]
