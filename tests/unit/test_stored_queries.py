"""The proof a stored AgentStep keeps: each query's name, rows, ms and Cypher sha, and params within the budget."""

import json

from oncall_brain.agents.loop import stored_queries
from oncall_brain.domain.models import QueryRun, cypher_sha


def test_params_past_the_budget_are_dropped_and_the_rest_kept():
    big = QueryRun(name="big", cypher="", params={"x": "y" * 3000}, rows=[], ms=1.0, readonly=True)
    small = QueryRun(name="small", cypher="MATCH (n) RETURN n", params={"id": "inc:a"}, rows=[{}], ms=0.5,
                     readonly=True)
    kept_big, kept_small = json.loads(stored_queries([big, small]))
    assert kept_big["name"] == "big" and kept_big["params"] is None and kept_big["row_count"] == 0
    assert kept_small["params"] == {"id": "inc:a"} and kept_small["row_count"] == 1 and kept_small["ms"] == 0.5
    assert kept_small["sha"] == cypher_sha("MATCH (n) RETURN n") != cypher_sha("MATCH (n) RETURN n.id")
