FROM python:3.13-slim

# Install PostgreSQL and Node.js 22
RUN apt-get update && apt-get install -y curl postgresql postgresql-contrib \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend backend
COPY frontend frontend
COPY run-container.sh run-container.sh

RUN chmod +x run-container.sh

RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir -r backend/requirements-dev.txt

RUN npm --prefix frontend ci

EXPOSE 8000 5173

CMD ["./run-container.sh"]

