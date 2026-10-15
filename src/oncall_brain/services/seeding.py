"""Load the seeded synthetic company into a tenant graph (idempotent) and keep a pristine copy for resets."""

import hashlib
import json

from oncall_brain.datagen import generate
from oncall_brain.ports import GraphRepository, GraphStore

# Order matters: edges MATCH nodes created by earlier statements.
INGEST = [("ingest_teams", "teams"), ("ingest_people", "people"), ("ingest_services", "services"),
          ("ingest_depends_on", "depends_on"), ("ingest_on_call", "on_call"), ("ingest_changes", "changes"),
          ("ingest_alerts", "alerts"), ("ingest_anomalies", "anomalies"), ("ingest_runbooks", "runbooks"),
          ("ingest_incidents", "incidents"), ("ingest_tickets", "tickets"), ("ingest_messages", "messages")]


def load(repo: GraphRepository, data: dict[str, list[dict]]) -> None:
    """Idempotent ingest: every statement MERGEs on stable ids, so loading twice changes nothing."""
    repo.ensure_schema()
    for query, key in INGEST:
        repo.write(query, rows=data[key])


def fingerprint(data: dict[str, list[dict]]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def seed(store: GraphStore, tenant: str, seed: int = 7) -> dict[str, int]:
    """Rebuild the tenant from scratch and snapshot it. Dropping first matters: the snapshot must hold
    only seed data, never incidents or runbooks left over from a rehearsal."""
    store.drop(tenant)
    data = generate(seed)
    repo = store.tenant(tenant)
    load(repo, data)
    repo.write("ingest_meta", version=fingerprint(data), seed=seed)
    store.snapshot(tenant)
    return {key: len(data[key]) for _, key in INGEST}


class TenantLimitReached(Exception):
    pass


def reset(store: GraphStore, tenant: str, seed_value: int | None = None, max_tenants: int | None = None) -> str:
    """Restore the pristine copy (GRAPH.COPY); seed from scratch if there is none (or it can't be copied).
    A new tenant costs two graphs, so callers facing the network pass a cap; existing tenants always reset."""
    # ponytail: check-then-seed race, so concurrent new-tenant resets can overshoot a little; fine for a soft cap.
    known = store.tenants()
    if max_tenants is not None and tenant not in known and len(known) >= max_tenants:
        raise TenantLimitReached(f"tenant limit reached ({max_tenants}); reset an existing tenant or raise MAX_TENANTS")
    with store.lock(tenant):
        if store.restore(tenant):
            rows = store.tenant(tenant).read("data_version").rows
            seed_value = seed_value or (rows[0]["seed"] if rows else None) or 7  # keep the tenant's own seed
            if rows and rows[0]["version"] == fingerprint(generate(seed_value)):
                return "restored"
        seed(store, tenant, seed_value or 7)  # no copy, or one built by an older generator
        return "seeded"
