# On-call Brain API + UI. Run with FalkorDB via docker-compose.yml: docker compose up --build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WEB_DIR=/app/web
WORKDIR /app

# Install the package before copying scripts/ and web/, so edits there reuse this layer.
COPY pyproject.toml ./
COPY src/ src/
RUN pip install .
COPY scripts/ scripts/
COPY web/ web/

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000

# Seed the default tenant only if its graph is missing, so a restart keeps incidents and learned runbooks.
# PORT is set by most container hosts (Render, Railway, Fly); 8000 locally.
CMD ["sh", "-c", "python -m scripts.seed --if-missing && exec uvicorn oncall_brain.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
