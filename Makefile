SHELL := /bin/bash
# On Harsh's machine everything (venv, caches, FalkorDB binaries) lives on the external HDD via env.sh.
# Elsewhere env.sh is absent and we fall back to ./.venv and ./.falkordb-bin.
ENV_SH ?= /media/harsh/MyPassport1/devenv/env.sh
E := [ -f $(ENV_SH) ] && . $(ENV_SH); \
	export VIRTUAL_ENV=$${VIRTUAL_ENV:-$(CURDIR)/.venv} FALKORDB_BIN=$${FALKORDB_BIN:-$(CURDIR)/.falkordb-bin}; \
	export PATH=$$VIRTUAL_ENV/bin:$$PATH;
TENANT ?= acme
PORT ?= 8000

.PHONY: setup falkordb-bin db db-stop seed dev mcp test test-unit lint demo docs snapshot

setup:
	$(E) if command -v uv >/dev/null; then uv venv -q --allow-existing --python 3.12 $$VIRTUAL_ENV && uv pip install -q --python $$VIRTUAL_ENV/bin/python -e ".[dev]"; \
	else python3.12 -m venv $$VIRTUAL_ENV && pip install -q -e ".[dev]"; fi
	$(E) python -c "import redislite" 2>/dev/null || [ -x "$$FALKORDB_BIN/redis-server" ] || \
	  (if command -v uv >/dev/null; then uv pip install -q --python $$VIRTUAL_ENV/bin/python falkordblite; else pip install -q falkordblite; fi) 2>/dev/null || \
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

test:
	$(E) pytest -q

test-unit:
	$(E) pytest -q tests/unit

lint:
	$(E) ruff check src scripts tests data

demo:
	$(E) python -m scripts.demo --tenant demo_$$(date +%s)

docs:
	$(E) python -m scripts.gen_queries_doc

snapshot:
	git log --oneline -40 > ../collab/GITLOG.txt
	git archive --format=tar.gz -o ../collab/snapshot.tar.gz HEAD
	@echo "snapshot written to ../collab/"
