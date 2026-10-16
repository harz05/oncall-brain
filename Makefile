SHELL := /bin/bash
# Optional machine-local environment file (e.g. to keep the venv, caches and FalkorDB binaries on another disk).
# When it is absent everything falls back to ./.venv and ./.falkordb-bin.
ENV_SH ?= ../../devenv/env.sh
E := [ -f $(ENV_SH) ] && . $(ENV_SH); \
	export VIRTUAL_ENV=$${VIRTUAL_ENV:-$(CURDIR)/.venv} FALKORDB_BIN=$${FALKORDB_BIN:-$(CURDIR)/.falkordb-bin}; \
	export PATH=$$VIRTUAL_ENV/bin:$$PATH;
TENANT ?= acme
PORT ?= 8000

.PHONY: setup falkordb-bin db db-stop seed dev mcp mcp-http serve headless test test-unit lint demo eval docs snapshot

setup:
	$(E) if command -v uv >/dev/null; then uv venv -q --allow-existing --python 3.12 $$VIRTUAL_ENV && uv pip install -q --python $$VIRTUAL_ENV/bin/python -e ".[dev]"; \
	else python3.12 -m venv $$VIRTUAL_ENV && pip install -q -e ".[dev]"; fi
	$(E) python -c "import redislite" 2>/dev/null || [ -x "$$FALKORDB_BIN/redis-server" ] || \
	  (if command -v uv >/dev/null; then uv pip install -q --only-binary falkordblite --python $$VIRTUAL_ENV/bin/python falkordblite; \
	   else pip install -q --only-binary falkordblite falkordblite; fi) 2>/dev/null || \
	  bash scripts/falkordb_bin.sh

falkordb-bin:
	$(E) bash scripts/falkordb_bin.sh

db:
	$(E) bash scripts/falkordb.sh start

db-stop:
	$(E) bash scripts/falkordb.sh stop

seed:
	$(E) python -m scripts.seed --tenant $(TENANT)

dev:
	$(E) uvicorn oncall_brain.api.app:app --reload --port $(PORT)

mcp:
	$(E) python -m oncall_brain.mcp_server

# Remote MCP (Claude Desktop / claude.ai connectors): Streamable HTTP on :8001, bearer token when API_TOKEN is set.
mcp-http:
	$(E) python -m oncall_brain.mcp_server --http --port 8001

# A deployment in one process (what the Dockerfile runs): UI + API at /, the MCP server at /mcp, /health. /mcp answers
# only with MCP_TOKEN (or API_TOKEN) set.
serve:
	$(E) uvicorn oncall_brain.serve:app --port $(PORT)

# The headless flow against a running `make dev`: alert in through the webhook, agents, status update out.
headless:
	$(E) python -m scripts.headless --tenant $(TENANT)

test:
	$(E) pytest -q

test-unit:
	$(E) pytest -q tests/unit

lint:
	$(E) ruff check src scripts tests

demo:
	$(E) python -m scripts.demo --tenant demo

eval:
	$(E) python -m scripts.eval --n 200

bench-concurrency:
	$(E) python -m scripts.concurrency

docs:
	$(E) python -m scripts.gen_queries_doc

# Dev-only: archive HEAD for an outside code reviewer working from ../collab.
snapshot:
	git log --oneline -40 > ../collab/GITLOG.txt
	git archive --format=tar.gz -o ../collab/snapshot.tar.gz HEAD
	@echo "snapshot written to ../collab/"
