FROM python:3.13-slim

# Install PostgreSQL and Node.js 223
RUN apt-get update && apt-get install -y curl postgresql postgresql-contrib \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add PostgreSQL binaries to PATH
ENV PATH="/usr/lib/postgresql/17/bin:${PATH}"

WORKDIR /app

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

