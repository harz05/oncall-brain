"""The two-act demo, end to end in the terminal: python -m scripts.demo [--tenant demo] [--cypher]

Act 1: checkout is slow -> agents find the payments-gw config change by traversal, refute 4 decoys.
       A human confirms the fix -> it becomes memory (CAUSED_BY + a learned Runbook).
Act 2: refunds is slow (3 days later) -> recalled from act 1, solved in one check.
Proof: act 2 replayed on a fresh graph with no act-1 memory takes the long road.
Act 3: three alerts at once -> correlated over the dependency graph (shared red upstream, ranked by convergence);
       without that correlation the agent would blame a change that only explains one of the alerts.
Exits non-zero if the story does not hold, so `make demo` doubles as an end-to-end check.
"""

import argparse
import sys

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS
from oncall_brain.services.respond import resolve, respond
from oncall_brain.services.seeding import reset
from oncall_brain.wiring import make_llm, make_store

B, DIM, R, G, Y = "\033[1m", "\033[2m", "\033[0m", "\033[32m", "\033[33m"


def show(title: str, run: dict, cypher: bool) -> None:
    print(f"\n{B}=== {title}: {run['alert']['alert']} ({run['incident_id']}) ==={R}  {DIM}planner: {run['planner']}{R}")
    for s in run["steps"]:
        q = [x for x in s.queries if x.name != "incident_board"]
        print(f"{s.seq:>2} {Y}{s.role:<12}{R} {s.tool:<24} {s.summary}")
        print(f"   {DIM}why: {s.reason}  [{len(q)} queries, {sum(x.row_count for x in q)} rows, "
              f"{sum(x.ms for x in q):.1f} ms]{R}")
        if cypher:
            for x in q:
                print(f"   {DIM}-- {x.name} ({'RO' if x.readonly else 'W'}) params={_short(x.params)}{R}")
                print("\n".join(f"   {DIM}   {ln}{R}" for ln in x.cypher.splitlines() if not ln.startswith("//")))
    o = run["outcome"]
    rc = o["root_cause"]
    print(f"{G}root cause:{R} {rc['change']} on {rc['service']}: {rc['reason']}" if rc else "no root cause found")
    for r in o["refuted"]:
        print(f"{DIM}ruled out:{R} {r['change']} ({r['reason']})")
    for label, pick, ok in (("flat change log (newest change)", o["baseline_pick"], o["baseline_correct"]),
                            ("anomaly-aware change log (no graph)", o["anomaly_baseline_pick"],
                             o["anomaly_baseline_correct"])):
        if pick:
            print(f"{label} would blame: {pick['change']} on {pick['service']} -> {'correct' if ok else 'WRONG'}")
    print(f"investigator tool calls: {o['investigator_calls']}, hypotheses checked: {o['hypotheses_checked']} "
          f"(culprit on check {o['checks_to_culprit']}), solved by memory: {o['memory']['solved_by_memory']}")
    if o["update_text"]:
        print(f"{DIM}--- status update ---{R}\n{o['update_text']}")


def _short(params: dict) -> dict:
    return {k: (f"[{len(v)} rows]" if isinstance(v, list) and len(v) > 3 else v) for k, v in params.items()}


class NoCorrelation(MockProvider):
    """The same planner, blind to the alert storm: each alert is investigated on its own."""

    name = "deterministic planner without alert correlation"

    def decide(self, role, board, tools):
        return super().decide(role, {**board, "storm": 0}, tools)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="demo")
    p.add_argument("--cypher", action="store_true", help="print every query each step ran")
    a = p.parse_args()
    store, llm = make_store(), make_llm()
    repo = store.tenant(a.tenant)

    print(f"tenant_{a.tenant}: {reset(store, a.tenant)} pristine graph")
    act1 = respond(repo, ACTS[1], llm)
    show("ACT 1", act1, a.cypher)
    cause = act1["outcome"]["root_cause"]
    if not cause:
        return 1
    res = resolve(repo, act1["incident_id"], cause["change"])
    print(f"\n{B}human confirms the fix ->{R} {res['summary']}")

    act2 = respond(repo, ACTS[2], llm)
    show("ACT 2", act2, a.cypher)

    reset(store, a.tenant)
    cold = respond(repo, ACTS[2], llm)
    o2, oc = act2["outcome"], cold["outcome"]
    print(f"\n{B}=== memory ablation: act 2 with vs without act 1 in the graph ==={R}")
    for label, o in (("with memory:   ", o2), ("without memory:", oc)):
        print(f"  {label} {o['investigator_calls']} investigator calls, {o['hypotheses_checked']} hypotheses "
              f"checked, culprit on check {o['checks_to_culprit']}")
    reset(store, a.tenant)
    act3 = respond(repo, ACTS[3], llm)
    show("ACT 3 (alert storm)", act3, a.cypher)
    reset(store, a.tenant)
    blind = respond(repo, ACTS[3], NoCorrelation())["outcome"]
    print(f"\n{B}=== correlation ablation: act 3 without correlating the alerts ==={R}")
    print(f"  with correlation:    blames {act3['outcome']['root_cause']['change']}")
    print(f"  without correlation: blames {blind['root_cause']['change']} (explains only one of the three alerts)")
    reset(store, a.tenant)  # leave the tenant pristine for the next run / the UI

    ok = (cause["change"] == "chg:pgw-pool-1" and not act1["outcome"]["baseline_correct"]
          and o2["memory"]["solved_by_memory"] and o2["root_cause"]["change"] == "chg:pgw-pool-2"
          and oc["root_cause"] and oc["investigator_calls"] > o2["investigator_calls"]
          and oc["hypotheses_checked"] > o2["hypotheses_checked"]
          and oc["checks_to_culprit"] > o2["checks_to_culprit"]
          and act3["outcome"]["root_cause"]["change"] == "chg:pg-conn-3"
          and blind["root_cause"]["change"] != "chg:pg-conn-3")
    print(f"\n{G + 'DEMO OK' if ok else 'DEMO FAILED'}{R}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
