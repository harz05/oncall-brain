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
CMD ["sh", "-c", "python -c 'from oncall_brain.config import get_settings; from oncall_brain.services.seeding import seed; from oncall_brain.wiring import make_store; t = get_settings().default_tenant; s = make_store(); s.exists(t) or print(\"seeded\", t, seed(s, t))' && exec uvicorn oncall_brain.api.app:app --host 0.0.0.0 --port 8000"]
