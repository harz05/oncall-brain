"""Load the seeded synthetic company into a tenant graph (idempotent) and keep a pristine copy for resets."""

from oncall_brain.datagen import generate
from oncall_brain.ports import GraphStore

# Order matters: edges MATCH nodes created by earlier statements.
INGEST = [("ingest_teams", "teams"), ("ingest_people", "people"), ("ingest_services", "services"),
          ("ingest_depends_on", "depends_on"), ("ingest_on_call", "on_call"), ("ingest_changes", "changes"),
          ("ingest_alerts", "alerts"), ("ingest_anomalies", "anomalies"), ("ingest_runbooks", "runbooks"),
          ("ingest_incidents", "incidents"), ("ingest_tickets", "tickets"), ("ingest_messages", "messages")]


def seed(store: GraphStore, tenant: str, seed: int = 7) -> dict[str, int]:
    repo = store.tenant(tenant)
    repo.ensure_schema()
    data = generate(seed)
    for query, key in INGEST:
        repo.write(query, rows=data[key])
    store.snapshot(tenant)
    return {key: len(data[key]) for _, key in INGEST}


def reset(store: GraphStore, tenant: str, seed_value: int = 7) -> str:
    """Restore the pristine copy (GRAPH.COPY); seed from scratch if there is none yet."""
    if store.restore(tenant):
        return "restored"
    seed(store, tenant, seed_value)
    return "seeded"
