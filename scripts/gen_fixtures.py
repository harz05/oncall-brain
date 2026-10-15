"""Regenerate web/fixtures/*.json (the UI's ?offline=1 mode) from the real code: python -m scripts.gen_fixtures"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from oncall_brain.api.app import app
from oncall_brain.datagen import ACTS, T1
from oncall_brain.wiring import make_store

OUT = Path(__file__).parents[1] / "web" / "fixtures"
TENANT = "fixtures_gen"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    c, base = TestClient(app), f"/api/tenants/{TENANT}"

    def dump(name: str, obj) -> None:
        (OUT / f"{name}.json").write_text(json.dumps(obj, indent=1))

    try:
        c.post(f"{base}/reset")
        dump("health", c.get("/api/health").json())
        dump("alerts", c.get(f"{base}/alerts").json())
        dump("graph", c.get(f"{base}/graph", params={"at": T1}).json())
        act1 = c.post(f"{base}/alerts/{ACTS[1]}/respond").json()
        dump("act1", act1)
        dump("resolve", c.post(f"{base}/incidents/{act1['incident_id']}/resolve",
                               json={"change_id": act1["outcome"]["root_cause"]["change"]}).json())
        dump("act2", c.post(f"{base}/alerts/{ACTS[2]}/respond").json())
        dump("act3", c.post(f"{base}/alerts/{ACTS[3]}/respond").json())
    finally:
        make_store().drop(TENANT)
    print(f"wrote {len(list(OUT.glob('*.json')))} fixtures to {OUT}")


if __name__ == "__main__":
    main()
