# Build context is the repo root:  docker compose build backend
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/growshed ./growshed
COPY --from=frontend /app/dist ./static
ENV GROWSHED_STATIC_DIR=/app/static \
    GROWSHED_CONFIG_PATH=/config/config.yaml \
    GROWSHED_DB_PATH=/data/growshed.db
EXPOSE 8000
CMD ["uvicorn", "growshed.main:app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
