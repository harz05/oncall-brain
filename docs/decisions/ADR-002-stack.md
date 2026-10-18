# ADR-002: Stack and how FalkorDB runs

- Status: accepted, 2026-10-15
- Deciders: autonomous build agent (Claude Code), within the defaults of Harsh's brief; reviewed by Harsh

## Context
- The rules require FalkorDB as the primary database, doing real work. Data must be synthetic.
- The dev machine runs Ubuntu 22.04 with glibc 2.35. The easy embedded route, the `falkordblite` wheel (which bundles redis-server and the FalkorDB module), needs glibc 2.39, so it does not install here.
- No `docker pull` on the dev machine: images land on an internal disk that is nearly full. Everything (venv, caches, binaries, data) must live on the external drive.
- No LLM key is available. The product has to run end to end without one.
- One builder with AI help, and hours not weeks. The judges must be able to run it from a clean checkout.

## Decision
- **Language and libraries:** Python 3.12, the official `falkordb` client (1.8), FastAPI + uvicorn, pydantic v2 at every boundary, pydantic-settings for config, the official `mcp` SDK, pytest and ruff. These are the brief's defaults. Nothing here needed an override.
- **FalkorDB on the dev machine:** FalkorDB's official prebuilt module, release **v4.22.0, rhel8 build** (`falkordb-rhel8-x64.so`, needs only glibc >= 2.28), loaded into **redis 8.10.2 built from source**. Both downloads are pinned by version and sha256 in `scripts/falkordb_bin.sh`. They are installed into `$FALKORDB_BIN` on the external drive. `scripts/falkordb.sh` (`make db` / `make db-stop`) starts and stops a native server with `--loadmodule`, with data in `$FALKORDB_DATA`. On hosts with glibc >= 2.39 the same script uses the binaries bundled in `falkordblite` instead.
- **FalkorDB for judges and hosting:** `docker-compose.yml` pins `falkordb/falkordb:v4.22.0` next to the app container, the same FalkorDB version as the dev machine, and publishes ports on 127.0.0.1 only. For a live deployment, FalkorDB Cloud plus the same container on Render or any Docker VM ([DEPLOY.md](../DEPLOY.md)); `Settings` accepts `FALKORDB_URL` (`rediss://...`) or host, port, username, password and `FALKORDB_SSL`.
- **Graph layout:** one graph per tenant (`tenant_<name>`) plus a pristine copy (`pristine_<name>`) made with `GRAPH.COPY` for instant demo resets. Seeding drops and rebuilds the tenant and stamps a `Meta` node with a fingerprint of the generated data, so a reset never restores a copy built by an older generator.
- **Concurrency:** a per-tenant redis-py `Lock` in the same server serialises agent runs on a tenant, across processes. No extra infrastructure.
- **Queries:** Cypher lives only in `adapters/falkordb/queries/*.cypher`. Each statement has a `// name:` and a `// purpose:` header, is loaded by name and is always parameterised. Reads go through `GRAPH.RO_QUERY`, writes through `GRAPH.QUERY`. `docs/QUERIES.md` is generated from these files.
- **No ORM or OGM, and no agent framework.** The loop is hand-written (ADR-003).
- **Frontend:** a no-build static web app (HTML + ES modules, graph library from a CDN), served by FastAPI. No node_modules and no bundler.
- **No embeddings in the core path** (ADR-004). The brief's `EmbeddingProvider` port was not built, because nothing uses it yet.

## Consequences
- Works on this machine without Docker and without root. Nothing touches the internal disk.
- The FalkorDB version is identical across the dev machine (v4.22.0 module) and docker-compose (v4.22.0 image), so a query that works locally works for judges.
- The first `make falkordb-bin` compiles redis from source, which takes a few minutes. Later runs reuse the binaries.
- `GRAPH.RO_QUERY` gives a guarantee no code review can: the database refuses writes from read tools (`test_read_tools_cannot_write`).
- `GRAPH.COPY` makes "reset the demo" a sub-second operation, and makes the before-and-after comparisons in `make demo` cheap. It forks like `BGSAVE`, so a copy that overlaps a background save fails with "could not fork"; the adapter retries with backoff.
- Named query files are easy to review and to list for the judges ("the Cypher the product depends on"). The cost is that a wrong query name is only caught at runtime, so `tests/unit/test_catalogue.py` checks that every name the code uses exists and has a purpose line.
- Sync FastAPI handlers run in uvicorn's thread pool, and the client uses a connection pool. That is enough here. The async client exists if we ever need it.

## Alternatives considered
- **`falkordblite` everywhere.** Simplest, but it does not install on glibc 2.35. It is kept as the automatic path on newer hosts.
- **Docker locally (`falkordb/falkordb` image).** Ruled out by the no-`docker pull` constraint. It is kept for judges in docker-compose.
- **Building FalkorDB from source.** Long build and a large toolchain. The official rhel8 module already works on old glibc.
- **Another graph database (Neo4j, Memgraph) or Postgres with recursive CTEs.** Rule 1 requires FalkorDB. Beyond that, FalkorDB gives us cheap per-tenant graphs in one process, `GRAPH.COPY` and `GRAPH.RO_QUERY`, which we lean on.
- **GraphRAG-SDK.** It builds a knowledge graph from unstructured text and answers questions through an LLM. Our data is already structured (services, edges, changes), extraction adds nothing, and it needs an LLM key we do not have. It is a good fit later for ingesting real postmortems.
- **An OGM or query builder.** It hides the Cypher that judges want to read, and is one more dependency for about 50 short statements.
- **A Node/TypeScript stack.** No advantage for this problem. Python is where the FalkorDB client, MCP SDK and our tests are strongest.
