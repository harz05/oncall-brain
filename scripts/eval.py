"""Does the graph agent find the planted cause where flat methods don't?  python -m scripts.eval --n 30 [--tenant eval]

For seeds 1..N: load scenarios.scenario(seed) into a fresh tenant graph, run the full respond() loop
(triage -> investigator -> comms, deterministic planner) and score the root cause it marks SUPPORTED against
the planted truth, next to three baselines that see the same change log without the graph. Prints the per-seed
table and rewrites docs/EVAL.md. Drops the tenant at the end.
"""

import argparse
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.scenarios import anomaly_pick, keyword_pick, scenario
from oncall_brain.services.respond import respond
from oncall_brain.services.seeding import INGEST
from oncall_brain.wiring import make_store

DOC = Path(__file__).parents[1] / "docs" / "EVAL.md"
BOARD = "incident_board"  # the planner's observe step, read before every decision; reported on its own row
# key -> (accuracy-table label, uses the graph, per-seed column); strongest baseline first.
METHODS = {"graph": ("graph agent (On-call Brain)", "yes", "graph agent"),
           "anomaly": ("anomaly-aware change log: change behind the first service to go red", "no", "anomaly-aware"),
           "keyword": ("keyword match: summary vs alert name", "no", "keyword"),
           "flat": ("flat change log: newest change in window", "no", "flat log")}


def load(store, tenant: str, data: dict):
    store.drop(tenant)
    repo = store.tenant(tenant)
    repo.ensure_schema()
    for query, key in INGEST:
        repo.write(query, rows=data[key])
    return repo


def checks(run: dict) -> list[dict]:
    return [s.data for s in run["steps"] if s.tool == "check_hypothesis" and s.data]


def why_wrong(run: dict, sc: dict, got: str | None) -> str:
    """The agent's own verdict reasons, so a miss explains itself in the report."""
    o = run["outcome"]
    truth = next((c for c in checks(run) if c["change"] == sc["truth_change"]), None)
    out = [f"truth judged {truth['verdict']}: {truth['reason']}" if truth
           else f"truth never checked ({o['hypotheses_checked']} checks)"]
    if got:
        out.append(f"supported {got}: {o['root_cause']['reason']}")
    return "; ".join(out) + f" (anomaly planted along {' -> '.join(s[4:] for s in sc['truth_path'])})"


def run_seed(store, tenant: str, seed: int, tool_ms: dict[str, list[float]]) -> dict:
    sc = scenario(seed)
    repo = load(store, tenant, sc["data"])
    t0 = time.perf_counter()
    run = respond(repo, sc["alert_id"], MockProvider())
    ms = (time.perf_counter() - t0) * 1000
    for s in run["steps"]:
        tool_ms[BOARD] += [q.ms for q in s.queries if q.name == BOARD]
        if s.tool != "handoff":
            tool_ms[s.tool].append(sum(q.ms for q in s.queries if q.name != BOARD))
    o, truth, d = run["outcome"], sc["truth_change"], sc["data"]
    got = (o["root_cause"] or {}).get("change")
    # The baselines read the same rows the graph was loaded from, in plain Python: no traversal.
    picks = {"graph": got, "anomaly": (anomaly_pick(d["changes"], d["anomalies"], d["alerts"][0]) or {}).get("id"),
             "keyword": (keyword_pick(d["changes"], d["alerts"][0]) or {}).get("id"),
             "flat": (o["baseline_pick"] or {}).get("change")}
    letter = {v: k for k, v in sc["decoys"].items()}
    refuted = {c["change"] for c in checks(run) if c["verdict"] == "refutes"}
    return {"seed": seed, "alert": sc["alert_id"].removeprefix("alert:"), "cause": sc["truth_path"][-1][4:],
            "hops": len(sc["truth_path"]) - 1, "decoys": "".join(sc["decoys"]),
            **{m: p == truth for m, p in picks.items()},
            "fooled": {m: letter.get(p, "none" if p is None else "other") for m, p in picks.items() if p != truth},
            "calls": o["investigator_calls"],
            "checks": o["hypotheses_checked"], "ms": ms,
            "refuted": {k for k, v in sc["decoys"].items() if v in refuted},
            "memory_misled": bool(o["memory"]["suspects"]),
            "why": None if got == truth else why_wrong(run, sc, got)}


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def ok(b: bool) -> str:
    return "yes" if b else "no"


def seed_table(rows: list[dict]) -> str:
    out = ["| seed | alert | true cause (hops) | decoys | " + " | ".join(m[2] for m in METHODS.values())
           + " | inv. calls | checks | respond ms |", "|---" * (7 + len(METHODS)) + "|"]
    out += [f"| {r['seed']} | {r['alert']} | {r['cause']} ({r['hops']}) | {r['decoys']} | "
            + " | ".join(ok(r[m]) for m in METHODS) + f" | {r['calls']} | {r['checks']} | {r['ms']:.0f} |"
            for r in rows]
    return "\n".join(out)


def stats(xs: list[float]) -> str:
    return f"{statistics.mean(xs):.1f} | {pct(xs, 50):.1f} | {pct(xs, 95):.1f}"


METHOD = """\
## Method

Each seed builds a fresh graph (`src/oncall_brain/scenarios.py`): the {services}-service org, owners, on-call
rotation and dependency map from `datagen.py`, then one randomised incident:

- **Alert**: a random service that has dependencies, symptom latency or errors.
- **Truth**: one deploy or config change 20-110 min before the alert, on a service drawn uniformly from the
  alerting service itself and its live dependencies 1-3 hops away. Anomalies follow one randomly chosen
  shortest live dependency path from the changed service back to the alerting service, minutes apart.
- **Decoys**, each fooling a method without the graph and refuted by a different graph fact:
  - **a** the newest change in the 2 h window, on a service outside the alert's dependency closure, with
    an anomaly (no dependency path). Planted in every seed.
  - **b** a change on another dependency, rolled back before the alert (rollback time on the Change node).
  - **c** a change on a dependency off the propagation path with no anomaly (anomaly check).
  - **d** about half the seeds: change + anomaly on a service the alert *used to* depend on; that
    DEPENDS_ON edge was retired days earlier (temporal edge validity).
  - **e** about half the seeds: a resolved past incident with the same symptom whose cause service is on
    the path, but nothing changed there in the window (memory that must not mislead).
- **Noise**: 60 changes and 25 anomalies outside the window.
- Change summaries get a random flavour ("latency fix", "5xx alert noise", ...) with the same odds for
  truth, decoys and noise, so keyword overlap is not planted in either direction.

Methods compared, all over the same change log (the anomaly-aware rule also reads the anomaly feed). The
baselines are plain Python over the scenario rows, with no graph traversal:

- **Graph agent**: `services.respond.respond()` with the deterministic planner (`MockProvider`): recall,
  multi-hop suspects from `path_suspects` (investigate.cypher), then `check_hypothesis` on each. Correct iff the change
  it marks SUPPORTED is the planted truth.
- **Anomaly-aware change log** (`scenarios.anomaly_pick`), the strongest simple rule without the graph we
  found: drop changes rolled back before the alert, keep those whose own service shows an anomaly between
  the change and the alert, and blame the one whose service went red first (a cause goes red before what
  it breaks), ties to the newest. Decoy *a* goes red after the truth does, *b* is rolled back and *c* stays
  quiet, so only *d* can fool it: a change plus anomaly on a retired dependency looks exactly like a real
  upstream cause unless you know that `DEPENDS_ON` edge ended days ago. It blames *d* whenever *d*'s service
  went red first, and is right in every seed without *d*. Two variants scored lower and are not reported:
  "newest such change" blames *a* every time (it has its own anomaly), and keeping only the alerting
  team's services misses causes on other teams' dependencies.
- **Keyword match**: the in-window change whose summary shares most words with the alert name, ties to
  the newest (`scenarios.keyword_pick`). A stand-in for search over the change log without the graph. It
  is right mostly when the cause is the alerting service itself, whose name is in the alert name;
  otherwise a decoy wins, by name when it sits on the alerting service (often the rolled-back *b*) or by
  recency on ties (*a*).
- **Flat change log**: the newest change in the window anywhere (`recent_changes` in investigate.cypher, no traversal;
  `outcome.baseline_pick`). Always blames *a*, by construction.
"""

LIMITS = """\
## Limitations (read before quoting the numbers)

- **Synthetic.** One {services}-service org and one alert time. Real telemetry is messier: missing or
  late anomalies, anomalies with no change behind them, several real changes at once.
- **Same authors.** The generator, the checks and the agent were written by the same team, and the decoy
  types mirror the facts the agent checks (live path, edge validity, rollback, anomaly propagation). This
  shows those checks are implemented correctly and hold up on random topologies, not that they are the
  right checks for real incidents.
- **The flat baseline loses by construction**: decoy *a* is always the newest change in the window. Its
  row shows the agent is not fooled by recency, not how often "newest change" is right in practice.
- **The anomaly-aware row is the fair comparison, and the generator is kind to it.** Anomalies never go
  missing, and the only unrelated anomaly in the window (decoy *a*'s) always comes after the truth's, so
  "first service to go red" is right whenever no retired dependency is planted. Real incidents have
  unrelated earlier blips and silent services, which would cost it more. Read its gap to the graph agent
  as what one graph fact (edge validity at alert time) is worth on this generator, not as a general
  margin. This baseline was added after review; the agent was not tuned to it.
- **Deterministic planner.** No LLM in the loop; an LLM planner would add run-to-run variance.
- **One change-caused root cause per scenario.** "No change, it's capacity" incidents are not in the set.
- **Latency** is a laptop against a local FalkorDB with a few hundred nodes per graph: it says the loop
  is interactive, not how it scales.
"""


def report(rows: list[dict], tool_ms: dict[str, list[float]], services: int) -> str:
    n = len(rows)

    def acc(key: str) -> str:
        k = sum(r[key] for r in rows)
        return f"{k}/{n} | {100 * k / n:.0f}%"

    def wrong(key: str) -> str:
        c = Counter(r["fooled"][key] for r in rows if key in r["fooled"])
        return ", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "-"

    planted = {d: sum(d in r["decoys"] for r in rows) for d in "abcd"}
    refuted = {d: sum(d in r["refuted"] for r in rows) for d in "abcd"}
    e_planted = sum("e" in r["decoys"] for r in rows)
    fails = [r for r in rows if not r["graph"]]
    lines = [
        "# Eval: graph agent vs non-graph baselines", "",
        f"Generated by `python -m scripts.eval --n {n}` against a live FalkorDB. Every scenario is deterministic "
        "per seed, so rerunning reproduces the table (latencies aside).", "",
        METHOD.format(services=services),
        f"## Accuracy (N={n})", "",
        "| method | uses the graph | correct | accuracy | wrong picks, by decoy |", "|---|---|---|---|---|",
        *[f"| {label} | {graph} | {acc(m)} | {wrong(m)} |" for m, (label, graph, _) in METHODS.items()], "",
        "Wrong picks name the decoy the method blamed (*none*: it blamed nothing). Decoys planted: "
        + ", ".join(f"{d} {planted[d]}" for d in "abcd") + ".", "",
        f"Effort per incident: {statistics.mean(r['calls'] for r in rows):.1f} investigator tool calls and "
        f"{statistics.mean(r['checks'] for r in rows):.1f} hypotheses checked on average.", "",
        "Decoys on the board and refuted by the graph: "
        + ", ".join(f"{d} {refuted[d]}/{planted[d]}" for d in "abcd")
        + " (d only reaches the board when it is among the 5 newest changes). "
        f"Misleading memory (e) planted in {e_planted} seeds; memory suggested a suspect in "
        f"{sum(r['memory_misled'] for r in rows)}.", "",
        "## Latency", "",
        "| measure | calls | mean ms | p50 ms | p95 ms |", "|---|---|---|---|---|",
        f"| respond() wall time per incident (all roles, incl. writes) | {n} | {stats([r['ms'] for r in rows])} |",
    ]
    lines += [f"| tool `{t}`: its queries per call | {len(xs)} | {stats(xs)} |"
              for t, xs in sorted(tool_ms.items(), key=lambda kv: -statistics.mean(kv[1])) if t != BOARD]
    lines += [f"| planner observe: `{BOARD}` read per decision | {len(tool_ms[BOARD])} | {stats(tool_ms[BOARD])} |",
              "", "## Per seed", "", seed_table(rows), "", "## Graph agent failures", ""]
    lines += [f"- seed {r['seed']} ({r['alert']}, cause {r['cause']}): {r['why']}" for r in fails] or ["None."]
    lines += ["", LIMITS.format(services=services)]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--tenant", default="eval")
    a = p.parse_args()
    store = make_store()
    rows: list[dict] = []
    tool_ms: dict[str, list[float]] = defaultdict(list)
    try:
        for seed in range(1, a.n + 1):
            rows.append(run_seed(store, a.tenant, seed, tool_ms))
            r = rows[-1]
            print(f"seed {seed:>3} {r['alert']:<28} graph={'ok ' if r['graph'] else 'MISS'} "
                  + " ".join(f"{m}={'ok ' if r[m] else 'miss'}" for m in list(METHODS)[1:])
                  + f" {r['ms']:.0f} ms" + (f"  <- {r['why']}" if r["why"] else ""))
    finally:
        store.drop(a.tenant)
    doc = report(rows, tool_ms, len(scenario(1)["data"]["services"]))
    DOC.write_text(doc + "\n")
    print("\n## Accuracy" + doc.split("## Accuracy", 1)[1].split("## Per seed", 1)[0])
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
