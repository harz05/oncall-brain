"""Load the seeded synthetic company into a tenant graph (idempotent) and keep a pristine copy for resets."""

import hashlib
import json

from oncall_brain.datagen import generate
from oncall_brain.ports import GraphRepository, GraphStore

# Order matters: edges MATCH nodes created by earlier statements (docs mention changes, incidents and initiatives,
# tickets join initiatives and mention docs, chat mentions tickets).
INGEST = [("ingest_teams", "teams"), ("ingest_people", "people"), ("ingest_services", "services"),
          ("ingest_depends_on", "depends_on"), ("ingest_on_call", "on_call"), ("ingest_changes", "changes"),
          ("ingest_alerts", "alerts"), ("ingest_anomalies", "anomalies"), ("ingest_runbooks", "runbooks"),
          ("ingest_incidents", "incidents"), ("ingest_initiatives", "initiatives"), ("ingest_docs", "docs"),
          ("ingest_doc_links", "docs"), ("ingest_tickets", "tickets"), ("ingest_messages", "messages")]


def load(repo: GraphRepository, data: dict[str, list[dict]]) -> None:
    """Idempotent ingest: every statement MERGEs on stable ids, so loading twice changes nothing."""
    repo.ensure_schema()
    for query, key in INGEST:
        repo.write(query, rows=data.get(key, []))  # eval scenarios and bench graphs carry no initiatives


def fingerprint(data: dict[str, list[dict]]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def seed(store: GraphStore, tenant: str, seed: int = 7) -> dict[str, int]:
    """Rebuild the tenant from scratch and snapshot it, holding the tenant's lock (a reset or an agent run waits)."""
    with store.lock(tenant):
        return _seed(store, tenant, seed)


def _seed(store: GraphStore, tenant: str, seed: int = 7) -> dict[str, int]:
    """seed() for a caller that already holds the tenant's lock (reset). The company is built on an empty staging graph
    and published whole (GRAPH.COPY to the pristine copy, then RENAME over the tenant), so the snapshot holds only seed
    data, never incidents, runbooks or a visitor's question, and nothing reads or writes a half-built tenant meanwhile
    (the watchdog re-seeds a live site after a database restart)."""
    data = generate(seed)
    repo = store.staging(tenant)
    load(repo, data)
    repo.write("ingest_meta", version=fingerprint(data), seed=seed)
    store.publish(tenant)
    return {key: len(data[key]) for _, key in INGEST}


class TenantLimitReached(Exception):
    pass


def reset(store: GraphStore, tenant: str, seed_value: int | None = None, max_tenants: int | None = None) -> str:
    """Restore the pristine copy (GRAPH.COPY); seed from scratch if there is none (or it can't be copied).
    A new tenant costs two graphs, so callers facing the network pass a cap; existing tenants always reset."""
    # limit: check-then-seed race, so concurrent new-tenant resets can overshoot a little; fine for a soft cap.
    known = store.tenants()
    if max_tenants is not None and tenant not in known and len(known) >= max_tenants:
        raise TenantLimitReached(f"tenant limit reached ({max_tenants}); reset an existing tenant or raise MAX_TENANTS")
    with store.lock(tenant):
        if store.restore(tenant):
            repo = store.tenant(tenant)
            rows = repo.read("data_version").rows
            seed_value = seed_value or (rows[0]["seed"] if rows else None) or 7  # keep the tenant's own seed
            if rows and rows[0]["version"] == fingerprint(generate(seed_value)):
                return "restored"
        _seed(store, tenant, seed_value or 7)  # no copy, or one built by an older generator
        return "seeded"
