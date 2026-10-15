from oncall_brain.domain.planner import next_decision


def board(steps=(), hyps=(), recalls=(), cause=None):
    return {"incident": {"id": "inc:x", "service": "svc:checkout"},
            "steps": [{"tool": t, "target": tg, "role": "?"} for t, tg in steps],
            "hypotheses": list(hyps), "recalls": list(recalls), "cause_service": cause}


def hyp(i, status="open", source="dependency-path", hops=1, at=0, svc="svc:a"):
    return {"id": i, "change_id": "chg:" + i, "service": svc, "status": status, "source": source, "hops": hops,
            "at": at}


def test_triage_order_then_handoff():
    assert next_decision("triage", board()).tool == "blast_radius"
    assert next_decision("triage", board([("blast_radius", "svc:checkout")])).tool == "page_on_call"
    d = next_decision("triage", board([("blast_radius", "svc:checkout"), ("page_on_call", "svc:checkout")]))
    assert d.action == "done" and d.handoff_to == "investigator"


def test_investigator_recalls_first_and_uses_strong_memory():
    assert next_decision("investigator", board()).tool == "recall_similar"
    b = board([("recall_similar", "inc:x")], recalls=[{"incident": "inc:old", "score": 3}])
    assert next_decision("investigator", b).tool == "hypothesize_from_memory"


def test_weak_memory_goes_straight_to_traversal():
    b = board([("recall_similar", "inc:x")], recalls=[{"incident": "inc:old", "score": 2}])
    assert next_decision("investigator", b).tool == "propose_hypotheses"


def test_checks_memory_suspects_first_then_nearest_then_newest():
    hyps = [hyp("far", hops=3, at=50), hyp("near_old", hops=1, at=10), hyp("near_new", hops=1, at=20),
            hyp("mem", source="memory", hops=4)]
    b = board([("recall_similar", "inc:x"), ("propose_hypotheses", "inc:x")], hyps)
    assert next_decision("investigator", b).args == {"hypothesis_id": "mem"}
    hyps[-1]["status"] = "refuted"
    assert next_decision("investigator", b).args == {"hypothesis_id": "near_new"}


def test_supported_and_nothing_open_hands_off_to_comms():
    b = board([("recall_similar", "inc:x")], [hyp("a", status="supported"), hyp("b", status="refuted")])
    d = next_decision("investigator", b)
    assert d.action == "done" and d.handoff_to == "comms"


def test_memory_refuted_falls_back_to_traversal_then_gives_up():
    b = board([("recall_similar", "inc:x"), ("hypothesize_from_memory", "inc:x")],
              [hyp("m", status="refuted", source="memory")], recalls=[{"incident": "inc:old", "score": 3}])
    assert next_decision("investigator", b).tool == "propose_hypotheses"
    b["steps"].append({"tool": "propose_hypotheses", "target": "inc:x", "role": "investigator"})
    d = next_decision("investigator", b)
    assert d.action == "done" and "non-change" in d.reason


def test_comms_pages_culprit_owner_names_an_expert_warns_dependents_then_posts():
    b = board(cause="svc:payments-gw")
    assert next_decision("comms", b).args == {"service": "svc:payments-gw"}
    b["steps"].append({"tool": "page_on_call", "target": "svc:payments-gw", "role": "comms"})
    assert next_decision("comms", b).args == {"service": "svc:payments-gw"}
    assert next_decision("comms", b).tool == "who_knows"
    b["steps"].append({"tool": "who_knows", "target": "svc:payments-gw", "role": "comms"})
    assert next_decision("comms", b).tool == "blast_radius"
    b["steps"].append({"tool": "blast_radius", "target": "svc:payments-gw", "role": "comms"})
    assert next_decision("comms", b).tool == "post_update"
