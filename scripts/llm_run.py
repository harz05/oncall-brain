"""A real model in the loop, on record: LLM_PROVIDER=ollama LLM_MODEL=qwen2.5:3b python -m scripts.llm_run

Plays the story exactly like scripts/demo.py (act 1, the human's confirm, act 2 with memory, act 2 on a reset graph
without it, act 3) with make_llm(), then once more with the deterministic planner for comparison. For every decision
it records the role, the tool and args, who decided (the model, or the planner after an "LLM fallback: ..."), the
reason and how long the decision took. Prints a markdown summary, writes the transcript as JSON and drops the tenant.
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS
from oncall_brain.domain.models import Decision
from oncall_brain.ports import LLMProvider
from oncall_brain.services.respond import resolve, respond
from oncall_brain.services.seeding import reset
from oncall_brain.wiring import make_llm, make_store

ROOT = Path(__file__).parents[1]
# Each run's alert and planted cause (scripts/demo.py checks the same ones). Act 1's is what the human confirms.
PLAN = {"act1": (ACTS[1], "chg:pgw-pool-1"), "act2": (ACTS[2], "chg:pgw-pool-2"),
        "act2_no_memory": (ACTS[2], "chg:pgw-pool-2"), "act3": (ACTS[3], "chg:pg-conn-3")}


class Timed:
    """Wraps a provider to keep each decision and its latency (the trace has neither the args nor the time)."""

    def __init__(self, llm: LLMProvider):
        self.llm, self.name, self.log = llm, llm.name, []

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        t0 = time.perf_counter()
        d = self.llm.decide(role, board, tools)
        self.log.append((d, (time.perf_counter() - t0) * 1000, len(json.dumps(board, default=str))))
        return d


def by(reason: str) -> str:
    if reason.startswith("LLM fallback:"):
        return "fallback"
    return "fallback (tool error)" if reason.startswith("fallback after tool error") else "model"


def act(repo, key: str, llm: Timed) -> tuple[dict[str, Any], dict[str, Any]]:
    (alert, truth), _ = PLAN[key], llm.log.clear()
    t0 = time.perf_counter()
    run = respond(repo, alert, llm)
    wall = time.perf_counter() - t0
    # One decide() per step after open_incident, except the loop's own out-of-budget handoff.
    steps = [s for s in run["steps"][1:] if not s.reason.startswith("step budget")]
    o, rc = run["outcome"], run["outcome"]["root_cause"] or {}
    return run, {
        "steps": [{"seq": s.seq, "role": s.role, "tool": s.tool, "by": by(s.reason), "ms": round(ms),
                   "board_chars": chars, "args": {k: v for k, v in d.args.items() if k != "incident_id"},
                   "reason": s.reason, "summary": s.summary} for s, (d, ms, chars) in zip(steps, llm.log, strict=True)],
        "outcome": {"root_cause": rc.get("change"), "correct": rc.get("change") == truth,
                    "investigator_calls": o["investigator_calls"], "hypotheses_checked": o["hypotheses_checked"],
                    "checks_to_culprit": o["checks_to_culprit"], "solved_by_memory": o["memory"]["solved_by_memory"],
                    "refuted": [r["change"] for r in o["refuted"]], "co_causes": o["co_causes"],
                    "paged": [x["handle"] for x in o["paged"]], "update_posted": bool(o["update_text"]),
                    "wall_s": round(wall, 1)}}


def story(store, tenant: str, llm: Timed) -> tuple[dict[str, Any], dict[str, Any]]:
    repo, out = store.tenant(tenant), {}
    reset(store, tenant)
    act1, out["act1"] = act(repo, "act1", llm)
    # The human's call is the planted cause, whatever the agents picked: a wrong pick must not become act 2's memory.
    resolve(repo, act1["incident_id"], PLAN["act1"][1])
    _, out["act2"] = act(repo, "act2", llm)
    reset(store, tenant)
    _, out["act2_no_memory"] = act(repo, "act2_no_memory", llm)
    reset(store, tenant)
    _, out["act3"] = act(repo, "act3", llm)
    return out, act1


def totals(acts: dict[str, Any]) -> dict[str, Any]:
    steps = [s for a in acts.values() for s in a["steps"]]
    ms = sorted(s["ms"] for s in steps)
    model = sum(s["by"] == "model" for s in steps)
    return {"decisions": len(steps), "by_model": model, "fallbacks": len(steps) - model,
            "fallback_rate": round((len(steps) - model) / len(steps), 3), "ms_p50": ms[len(ms) // 2],
            "ms_p95": ms[min(len(ms) - 1, int(0.95 * len(ms)))], "ms_mean": round(statistics.mean(ms)),
            "correct": f"{sum(a['outcome']['correct'] for a in acts.values())}/{len(acts)}"}


def markdown(rec: dict[str, Any]) -> str:
    out = [f"planner: {rec['planner']}", ""]
    for key, a in rec["acts"].items():
        out += [f"### {key}", "", "| # | role | tool | args | decided by | ms | reason |", "|---" * 7 + "|"]
        out += [f"| {s['seq']} | {s['role']} | {s['tool']} | {' '.join(map(str, s['args'].values())) or '-'} | "
                f"{s['by']} | {s['ms']} | {s['reason'][:110].replace('|', '/')} |" for s in a["steps"]]
        out.append("")
    out += ["| act | LLM root cause | correct | inv. calls | checks | culprit on check | deterministic: cause, calls, "
            "checks, culprit on check |", "|---|---|---|---|---|---|---|"]
    for key, a in rec["acts"].items():
        o, d = a["outcome"], rec["deterministic"][key]
        out.append(f"| {key} | {o['root_cause']} | {o['correct']} | {o['investigator_calls']} | "
                   f"{o['hypotheses_checked']} | {o['checks_to_culprit']} | {d['root_cause']}, "
                   f"{d['investigator_calls']}, {d['hypotheses_checked']}, {d['checks_to_culprit']} |")
    return "\n".join(out + ["", json.dumps(rec["totals"])])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="llmrun")
    p.add_argument("--out", type=Path, help="transcript JSON (default docs/llm_runs/<model>.json)")
    p.add_argument("--fixture", type=Path, help="also save act 1's full respond() output here (UI replay format)")
    a = p.parse_args()
    store, llm = make_store(), Timed(make_llm())
    try:
        acts, act1 = story(store, a.tenant, llm)
        det, _ = story(store, a.tenant, Timed(MockProvider()))
    finally:
        store.drop(a.tenant)
    rec = {"planner": llm.name, "date": time.strftime("%Y-%m-%d %H:%M"), "totals": totals(acts), "acts": acts,
           "deterministic": {k: v["outcome"] for k, v in det.items()}}
    out = a.out or ROOT / "docs" / "llm_runs" / (re.sub(r"[^\w.-]+", "_", llm.name.split(" ")[0]) + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, default=str) + "\n")
    if a.fixture:
        a.fixture.write_text(json.dumps(act1, indent=1, default=lambda m: m.model_dump(mode="json")))
    print(markdown(rec), f"\nwrote {out}", sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
