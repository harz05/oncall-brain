"""Does the graph agent find the planted cause where flat methods don't?  python -m scripts.eval --n 30 [--tenant eval]

For seeds 1..N: load scenarios.scenario(seed) into a fresh tenant graph, run the full respond() loop
(triage -> investigator -> comms, deterministic planner) and score the root cause it marks SUPPORTED against
the planted truth, next to three baselines that see the same change log without the graph. Prints the per-seed
table and rewrites docs/EVAL.md. Drops the tenant at the end.

--planner llm uses make_llm() (LLM_PROVIDER, LLM_MODEL) instead and also counts the steps that fell back to the
planner; it prints its numbers and leaves docs/EVAL.md alone (that file is the deterministic planner's record).
"""

import argparse
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.ports import LLMProvider
from oncall_brain.scenarios import anomaly_pick, keyword_pick, scenario
from oncall_brain.services.respond import respond
from oncall_brain.services.seeding import INGEST
from oncall_brain.wiring import make_llm, make_store

DOC = Path(__file__).parents[1] / "docs" / "EVAL.md"
BOARD = "incident_board"  # the planner's observe step, read before every decision; reported on its own row
# key -> (accuracy-table label, uses the graph, per-seed column); strongest baseline first.
METHODS = {"graph": ("graph agent (On-call Brain)", "yes", "graph agent"),
           "anomaly": ("anomaly-aware change log: change behind the first service to go red", "no", "anomaly-aware"),
           "keyword": ("keyword match: summary vs alert name", "no", "keyword"),
           "flat": ("flat change log: newest change in window", "no", "flat log")}
PERTURBATIONS = {"none": "none (only the planted story)", "noise": "noise: unrelated blips off the truth path",
                 "noise-on-c": "noise-on-c: a blip makes decoy c look red", "gap": "gap: an intermediate hop is silent",
                 "innocent": "innocent: a cascade victim deployed after the cause went red"}


def load(store, tenant: str, data: dict):
    store.drop(tenant)
    repo = store.tenant(tenant)
    repo.ensure_schema()
    for query, key in INGEST:
        repo.write(query, rows=data[key])
    return repo


def trace(run: dict, tool: str) -> list[dict]:
    return [s.data for s in run["steps"] if s.tool == tool and s.data]


def checks(run: dict) -> list[dict]:
    return trace(run, "check_hypothesis")


def why_wrong(run: dict, sc: dict, got: str | None, names: dict[str, str]) -> str:
    """The agent's own words from this run's trace (check_hypothesis verdicts, conclude's ranking), so a miss
    explains itself in the report."""
    said = {c["change"]: f"{c['verdict']}: {c['reason']}" for c in checks(run)}  # a re-check overwrites
    t = sc["truth_change"]
    out = [f"truth {t} " + said.get(t, f"never checked ({run['outcome']['hypotheses_checked']} checks)")]
    for c in trace(run, "conclude"):
        out += [f"truth {x['reason']}" for x in c.get("outranked", []) if x["change"] == t]
        out += [f"truth kept as co-cause ({x['reason']})" for x in c.get("co_causes", []) if x["change"] == t]
    out.append(f"picked {got} ({names.get(got, 'other')}) " + said.get(got, run["outcome"]["root_cause"]["reason"])
               if got else "picked nothing")
    silent = set(sc["perturbations"].get("gap", []))
    return "; ".join(out) + " (truth path " + " -> ".join(s[4:] + " [silent]" * (s in silent)
                                                         for s in sc["truth_path"]) + ")"


def run_seed(store, tenant: str, seed: int, tool_ms: dict[str, list[float]], llm: LLMProvider) -> dict:
    sc = scenario(seed)
    repo = load(store, tenant, sc["data"])
    t0 = time.perf_counter()
    run = respond(repo, sc["alert_id"], llm)
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
    letter = {v: k for k, v in sc["decoys"].items()} | {c: "innocent" for c in sc["perturbations"].get("innocent", [])}
    refuted = {c["change"] for c in checks(run) if c["verdict"] == "refutes"}
    return {"seed": seed, "alert": sc["alert_id"].removeprefix("alert:"), "cause": sc["truth_path"][-1][4:],
            "hops": len(sc["truth_path"]) - 1, "decoys": "".join(sc["decoys"]), "perturb": sorted(sc["perturbations"]),
            **{m: p == truth for m, p in picks.items()},
            "fooled": {m: letter.get(p, "none" if p is None else "other") for m, p in picks.items() if p != truth},
            "calls": o["investigator_calls"],
            "checks": o["hypotheses_checked"], "ms": ms, "decisions": len(run["steps"]) - 1,  # all but open_incident
            "fallbacks": sum(s.reason.startswith(("LLM fallback:", "fallback after tool error")) for s in run["steps"]),
            "refuted": {k for k, v in sc["decoys"].items() if v in refuted},
            "memory_misled": bool(o["memory"]["suspects"]),
            "why": None if got == truth else why_wrong(run, sc, got, letter)}


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def ok(b: bool) -> str:
    return "yes" if b else "no"


def seed_table(rows: list[dict]) -> str:
    out = ["| seed | alert | true cause (hops) | decoys | perturbations | " + " | ".join(m[2] for m in METHODS.values())
           + " | inv. calls | checks | respond ms |", "|---" * (8 + len(METHODS)) + "|"]
    out += [f"| {r['seed']} | {r['alert']} | {r['cause']} ({r['hops']}) | {r['decoys']} | {tags(r)} | "
            + " | ".join(ok(r[m]) for m in METHODS) + f" | {r['calls']} | {r['checks']} | {r['ms']:.0f} |"
            for r in rows]
    return "\n".join(out)


def tags(r: dict) -> str:
    return ", ".join(r["perturb"]) or "-"


def with_tag(rows: list[dict], tag: str) -> list[dict]:
    return [r for r in rows if (tag in r["perturb"] if tag != "none" else not r["perturb"])]


def frac(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "-"


def perturbation_table(rows: list[dict]) -> str:
    out = ["| seeds with | seeds | " + " | ".join(m[2] for m in METHODS.values()) + " |",
           "|---" * (2 + len(METHODS)) + "|"]
    for tag, label in PERTURBATIONS.items():
        rs = with_tag(rows, tag)
        out.append(f"| {label} | {len(rs)} | " + " | ".join(frac(sum(r[m] for r in rs), len(rs)) for m in METHODS)
                   + " |")
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
- **Perturbations**, so the window holds more than the planted story. Each seed is tagged with the ones it
  got (a seed can have several), and accuracy is reported per tag below:
  - **noise** (about half the seeds): 1-3 anomalies at random times in the window on dependencies of the
    alerting service that are off the truth path. No change behind them.
  - **noise-on-c**: one of those blips lands on decoy *c*'s service after its change, so *c* no longer looks
    quiet. Not placed on purpose: the spare services are few, so it happens in about 40% of noise seeds.
  - **gap** (about 20% of the seeds whose truth path has a hop in between): that hop's anomaly is dropped,
    as if its telemetry never arrived, so the propagation chain has a hole.
  - **innocent** (about 30% of the seeds whose cause is upstream of the alerting service): a change on a
    service between them, or on the alerting service itself, lands after the cause's service already went
    red, and its own service goes red a few minutes later. A cascade victim that happens to have a deploy:
    it is nearer the alert than the truth, and its anomaly follows its change.
- **Background**: 60 changes and 25 anomalies outside the window.
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
  it breaks), ties to the newest. Decoy *a* goes red after the truth does and *b* is rolled back. Without
  noise *c* stays quiet, so *d* is the main trap: a change plus anomaly on a retired dependency looks exactly
  like a real upstream cause unless you know that `DEPENDS_ON` edge ended days ago. Noise on *c* fools it
  too when the blip comes before the truth's first anomaly. Gaps and innocent changes do not: the cause's
  own anomaly is never dropped and the innocent change goes red after it. Two variants scored lower and are
  not reported:
  "newest such change" blames *a* every time (it has its own anomaly), and keeping only the alerting
  team's services misses causes on other teams' dependencies.
- **Keyword match**: the in-window change whose summary shares most words with the alert name, ties to
  the newest (`scenarios.keyword_pick`). A stand-in for search over the change log without the graph. It
  is right mostly when the cause is the alerting service itself, whose name is in the alert name;
  otherwise a decoy wins, by name when it sits on the alerting service (often the rolled-back *b*, or the
  innocent change, which is often on the alerting service) or by recency on ties (*a*).
- **Flat change log**: the newest change in the window anywhere (`recent_changes` in investigate.cypher, no traversal;
  `outcome.baseline_pick`). Always blames *a*, by construction.
"""

LIMITS = """\
## Limitations (read before quoting the numbers)

- **Synthetic.** One {services}-service org and one alert time, so alternative live paths are few; whether
  a gap hurts depends on whether another path happens to light up.
- **Same authors.** The generator, the checks and the agent were written by the same team, and the decoy
  types mirror the facts the agent checks (live path, edge validity, rollback, anomaly propagation). This
  shows those checks are implemented correctly and hold up on random topologies, not that they are the
  right checks for real incidents. The perturbations were added after mock judges called the first version
  (one decoy per verdict rule, nothing else in the window) built to be passed; the agent's ranking (onset-
  and upstream-aware leading cause, a monitoring gap as weaker support) changed in the same round, by the
  same team, knowing what the perturbations are. Not a blind test either.
- **The perturbation rates are ours.** The overall number moves with them; the per-perturbation rows say
  more. Gap seeds are few (it needs a truth path with a hop in between), so read that row with care.
- **The flat baseline loses by construction**: decoy *a* is always the newest change in the window. Its
  row shows the agent is not fooled by recency, not how often "newest change" is right in practice.
- **The anomaly-aware row is the fair comparison, and the generator is still kind to it.** The cause's own
  anomaly is never dropped and always follows its change within minutes, and noise only lands on dependencies
  of the alerting service, so only a blip on a changed service (decoy *c*) can go red before the truth.
  This baseline was added after review; the agent was not tuned to it.
- **What the perturbations still don't cover.** A silent cause service (the gap only hits hops in between;
  a changed service with no anomaly is refuted by design), more than one silent hop, late or out-of-order
  anomaly timestamps, a service on the truth path that was already flapping before the change, blips outside
  the alert's dependency closure, an innocent change off the truth path that goes red for its own reasons in
  the same minutes, several real causes at once, causes that are not changes (capacity, traffic), and changes
  missing from the change log.
- **Deterministic planner.** No LLM in the loop; an LLM planner would add run-to-run variance.
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
        "Wrong picks name the decoy the method blamed (*innocent*: the cascade victim's change; *none*: it blamed "
        "nothing). Decoys planted: " + ", ".join(f"{d} {planted[d]}" for d in "abcd") + ".", "",
        "## Accuracy by perturbation", "",
        "A seed with several perturbations counts in each of their rows.", "",
        perturbation_table(rows), "",
        f"Effort per incident: {statistics.mean(r['calls'] for r in rows):.1f} investigator tool calls and "
        f"{statistics.mean(r['checks'] for r in rows):.1f} hypotheses checked on average.", "",
        "Decoys on the board and refuted by the graph: "
        + ", ".join(f"{d} {refuted[d]}/{planted[d]}" for d in "abcd")
        + " (d only reaches the board when it is among the 5 newest changes). "
        f"Misleading memory (e) planted in {e_planted} seeds; memory suggested a suspect in "
        f"{sum(r['memory_misled'] for r in rows)}.", "",
        "## Graph agent misses", "",
        "Each in the agent's own words, from this run's `check_hypothesis` and `conclude` trace data.", "",
        *([f"- seed {r['seed']} [{tags(r)}] ({r['alert']}, cause {r['cause']}, {r['hops']} hops): {r['why']}"
           for r in fails] or ["None."]), "",
        "## Latency", "",
        "| measure | calls | mean ms | p50 ms | p95 ms |", "|---|---|---|---|---|",
        f"| respond() wall time per incident (all roles, incl. writes) | {n} | {stats([r['ms'] for r in rows])} |",
    ]
    lines += [f"| tool `{t}`: its queries per call | {len(xs)} | {stats(xs)} |"
              for t, xs in sorted(tool_ms.items(), key=lambda kv: -statistics.mean(kv[1])) if t != BOARD]
    lines += [f"| planner observe: `{BOARD}` read per decision | {len(tool_ms[BOARD])} | {stats(tool_ms[BOARD])} |",
              "", "## Per seed", "", seed_table(rows), "", LIMITS.format(services=services)]
    return "\n".join(lines)


def llm_summary(rows: list[dict], planner: str) -> int:
    """The LLM run's numbers, printed for docs/LLM_RUN.md; a sample this small would only blur EVAL.md."""
    n, d, f = len(rows), sum(r["decisions"] for r in rows), sum(r["fallbacks"] for r in rows)
    ms = [r["ms"] for r in rows]
    print(f"\n{planner}, N={n}\n\n| measure | value |\n|---|---|\n"
          + "\n".join(f"| {m[0]} correct | {frac(sum(r[k] for r in rows), n)} |" for k, m in METHODS.items())
          + f"\n| decisions (all roles) | {d} ({d / n:.1f} per incident) |\n| fell back to the planner | {frac(f, d)} |"
          f"\n| incidents with no fallback | {frac(sum(not r['fallbacks'] for r in rows), n)} |"
          f"\n| investigator calls / checks per incident | {statistics.mean(r['calls'] for r in rows):.1f} / "
          f"{statistics.mean(r['checks'] for r in rows):.1f} |"
          f"\n| respond() s per incident: mean / p50 / p95 | {stats([x / 1000 for x in ms]).replace(' |', ' /')} |"
          f"\n| ms per decision (mean) | {sum(ms) / d:.0f} |\n\n{perturbation_table(rows)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--tenant", default="eval")
    p.add_argument("--planner", choices=["mock", "llm"], default="mock", help="llm: make_llm(); EVAL.md untouched")
    a = p.parse_args()
    store, llm = make_store(), MockProvider() if a.planner == "mock" else make_llm()
    rows: list[dict] = []
    tool_ms: dict[str, list[float]] = defaultdict(list)
    try:
        for seed in range(1, a.n + 1):
            rows.append(run_seed(store, a.tenant, seed, tool_ms, llm))
            r = rows[-1]
            print(f"seed {seed:>3} {r['alert']:<28} {tags(r):<26} graph={'ok ' if r['graph'] else 'MISS'} "
                  + " ".join(f"{m}={'ok ' if r[m] else 'miss'}" for m in list(METHODS)[1:])
                  + f" {r['ms']:.0f} ms {r['fallbacks']}/{r['decisions']} fallbacks"
                  + (f"  <- {r['why']}" if r["why"] else ""))
    finally:
        store.drop(a.tenant)
    if a.planner == "llm":
        return llm_summary(rows, llm.name)
    doc = report(rows, tool_ms, len(scenario(1)["data"]["services"]))
    DOC.write_text(doc + "\n")
    print("\n## Accuracy" + doc.split("## Accuracy", 1)[1].split("## Latency", 1)[0])
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
