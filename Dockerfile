# On-call Brain in one container: web UI + HTTP API at /, the MCP server (Streamable HTTP) at /mcp, /health.
# FalkorDB comes from docker-compose.yml (docker compose up --build) or FALKORDB_URL (FalkorDB Cloud, render.yaml).
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
# PORT is set by most container hosts (Render, Railway, Fly); 8000 locally. oncall_brain.serve serves /mcp only with
# MCP_TOKEN (or API_TOKEN) set, and accepts the hostname Render or Railway set without ALLOWED_HOSTS.
CMD ["sh", "-c", "python -m scripts.seed --if-missing && exec uvicorn oncall_brain.serve:app --host 0.0.0.0 --port ${PORT:-8000}"]
