"""The headless flow, end to end, against a running API (make dev): an alert comes in through the webhook, the
three agents work it on the graph, and the status update comes out (to Slack too, when SLACK_WEBHOOK_URL is set).
Nothing else is open. Prints what the on-call engineer would read.

    python -m scripts.headless                       # checkout latency on tenant acme
    python -m scripts.headless --service svc:cart --symptom errors --name 'cart 5xx above 1%'
"""

import argparse
import sys

import httpx

from oncall_brain.datagen import T1


def clean(text: str) -> str:
    """Graph text can come from public input: show control characters (ESC sequences) escaped, never run them."""
    return "".join(ch if ch in "\n\t" or ch.isprintable() else repr(ch)[1:-1] for ch in text)

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--tenant", default="acme")
    p.add_argument("--service", default="svc:checkout")
    p.add_argument("--symptom", default="latency", choices=["latency", "errors", "saturation"])
    p.add_argument("--name", default="checkout p99 latency above 2s")
    # The synthetic company's changes sit around the story's dates, so the demo alert fires at act 1's time; a real
    # alerting tool sends no `at` and the alert is stamped now.
    p.add_argument("--at", default=str(T1), help="epoch seconds, or 'now' (default: the demo story's act-1 time)")
    a = p.parse_args()
    base = f"{a.api}/api/tenants/{a.tenant}"
    body = {"service": a.service, "symptom": a.symptom, "name": a.name}
    if a.at != "now":
        body["at"] = int(a.at)
    with httpx.Client(timeout=600) as c:
        health = c.get(f"{a.api}/api/health").json()
        db = "connected" if health["falkordb"] else "DOWN"
        print(f"API up · FalkorDB {db} · steps chosen by {health['planner']}")
        r = c.post(f"{base}/alerts", params={"respond": "true"}, json=body)
        if r.status_code == 404 and "unknown tenant" in r.text:
            c.post(f"{base}/reset")
            r = c.post(f"{base}/alerts", params={"respond": "true"}, json=body)
        r.raise_for_status()
        run = r.json()
    o, rc = run["outcome"], run["outcome"]["root_cause"]
    print(f"\nIncident {run['incident_id']} · {len(run['steps'])} steps · {run.get('llm_tokens', 0):,} tokens")
    if rc:
        conf = o["confidence"]
        print(clean(f"Likely cause: {rc['summary']} ({rc['service']}) · {conf['label']}: {conf['why']}"))
    else:
        print(f"No cause found: {o['confidence']['why']}")
    paged = ", ".join(f"{x['name']} ({x['team_name']})" for x in o["paged"])
    print(f"Paged: {paged or 'nobody'}")
    print(f"Ruled out: {len(o['refuted'])} · sources: {len(o['sources'])} · Slack: {run.get('slack')}")
    print("\n--- status update, as posted ---")
    print(clean(o["update_text"] or "(none)"))
    return 0 if rc else 1


if __name__ == "__main__":
    sys.exit(main())
