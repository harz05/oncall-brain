"""The two-act demo, end to end in the terminal: python -m scripts.demo [--tenant demo] [--cypher]

Act 1: checkout is slow -> agents find the payments-gw config change by traversal, refute 4 decoys.
       A human confirms the fix -> it becomes memory (CAUSED_BY + a learned Runbook).
Act 2: refunds is slow (3 days later) -> recalled from act 1, solved in one check.
Proof: act 2 replayed on a fresh graph with no act-1 memory takes the long road.
Exits non-zero if the story does not hold, so `make demo` doubles as an end-to-end check.
"""

import argparse
import sys

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
                print(f"   {DIM}{x.name} ({'RO' if x.readonly else 'W'}) params={_short(x.params)}{R}")
    o = run["outcome"]
    rc = o["root_cause"]
    print(f"{G}root cause:{R} {rc['change']} on {rc['service']}: {rc['reason']}" if rc else "no root cause found")
    for r in o["refuted"]:
        print(f"{DIM}ruled out:{R} {r['change']} ({r['reason']})")
    bp = o["baseline_pick"]
    if bp:
        print(f"flat change-log baseline would blame: {bp['change']} on {bp['service']} "
              f"-> {'correct' if o['baseline_correct'] else 'WRONG'}")
    print(f"investigator tool calls: {o['investigator_calls']}, "
          f"hypotheses checked: {o['hypotheses_checked']}, solved by memory: {o['memory']['solved_by_memory']}")
    if o["update_text"]:
        print(f"{DIM}--- status update ---{R}\n{o['update_text']}")


def _short(params: dict) -> dict:
    return {k: (f"[{len(v)} rows]" if isinstance(v, list) and len(v) > 3 else v) for k, v in params.items()}


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
    print(f"  with memory:    {o2['investigator_calls']} investigator calls, "
          f"{o2['hypotheses_checked']} hypotheses checked")
    print(f"  without memory: {oc['investigator_calls']} investigator calls, "
          f"{oc['hypotheses_checked']} hypotheses checked")
    reset(store, a.tenant)  # leave the tenant pristine for the next run / the UI

    ok = (cause["change"] == "chg:pgw-pool-1" and not act1["outcome"]["baseline_correct"]
          and o2["memory"]["solved_by_memory"] and o2["root_cause"]["change"] == "chg:pgw-pool-2"
          and oc["root_cause"] and oc["investigator_calls"] > o2["investigator_calls"]
          and oc["hypotheses_checked"] > o2["hypotheses_checked"])
    print(f"\n{G + 'DEMO OK' if ok else 'DEMO FAILED'}{R}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
