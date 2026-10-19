"""Generate docs/QUERIES.md from the named Cypher in adapters/falkordb/queries/*.cypher.

Run: python -m scripts.gen_queries_doc [--check]
The catalogue is generated so it cannot drift from what the code runs. --check exits 1 if the doc is stale,
and every run fails if a write statement is called through repo.read (GRAPH.RO_QUERY would reject it).
"""

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

from oncall_brain.adapters.falkordb.queries import all_queries
from oncall_brain.adapters.falkordb.repository import INDEXED_LABELS, PREFIX, PRISTINE, TIME_INDEXED
from oncall_brain.services.seeding import INGEST

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "QUERIES.md"
_WRITE = re.compile(r"\b(MERGE|CREATE|SET|DELETE|REMOVE)\b")
_STRING = re.compile(r"'[^']*'|\"[^\"]*\"")

INTROS = {  # file -> one-paragraph intro; files not listed still get a section
    "ingest.cypher": "**Ingest.** Loads the synthetic company: org, services, temporal dependencies, on-call shifts, "
    "changes, alerts, anomalies, past incidents and their sources. `services/seeding.py` runs them in order; each is "
    "`UNWIND $rows` + `MERGE` on a stable id, so re-seeding is idempotent.",
    "triage.cypher": "**Triage.** Opens the incident board, walks `DEPENDS_ON` backwards for the blast radius, and "
    "finds who is on call at alert time from the rotation edges.",
    "investigate.cypher": "**Investigate.** Recalls similar past incidents by graph structure, turns changes on the "
    "live dependency path into hypotheses, and tests each one (live path, retired path, anomaly propagation), "
    "recording `SUPPORTS` / `REFUTES` evidence.",
    "board.cypher": "**Board.** The agents' shared state. The planner re-reads the board before every decision and "
    "every step is persisted as an `AgentStep`, so handoffs between roles happen through the graph.",
    "comms_memory.cypher": "**Comms & memory.** The status update with its cited sources, and the human-confirmed "
    "resolution that becomes episodic (`CAUSED_BY`) and procedural (`Runbook`) memory.",
    "knowledge.cypher": "**Knowledge (company brain).** Who knows a service and where a change came from, answered "
    "from ownership, authorship, paging and source edges.",
    "api.cypher": "**API.** Read models for the HTTP API and the UI.",
    "coordination.cypher": "**Coordination.** What the processes share, as nodes in the `oncall_brain_coord` graph: "
    "the per-tenant run lock and Slack's replay guard are `Lease` nodes, and a UNIQUE constraint on `Lease.key` lets "
    "exactly one concurrent claimer create one; the throttles and the LLM token budget are `Counter` nodes. So the "
    "product needs graph commands plus RENAME and EXPIRE, never SET, INCR or EVAL (FalkorDB Cloud refuses those).",
    "reference.cypher": "**Reference implementations (tests and bench only).** The earlier, simpler forms of the hot "
    "traversals: they enumerate every path and then filter. `tests/integration/test_query_equivalence.py` checks the "
    "shipped forms return exactly the same rows, and `scripts/bench.py` times both (docs/PERF.md).",
}

# (capability, regex that finds it in a statement, why the product needs it)
CYPHER_FEATURES = [
    ("Variable-length paths with per-relationship temporal filters",
     r"all\(r IN relationships\(p\) WHERE r\.valid_from",
     "`DEPENDS_ON*0..6` where every hop must be valid at alert time: retired dependencies stop counting, "
     "which is how the legacy-billing decoy is refuted."),
    ("`shortestPath` in `WITH`", r"shortestPath\(",
     "A cheap lower bound on hops between a suspect and the alerting service, kept only if every edge on it is live "
     "at alert time; also tells a retired dependency apart from no dependency at all."),
    ("Per-hop filters on variable-length edges", r"\[e:DEPENDS_ON\*",
     "`[e:DEPENDS_ON*0..6]` with a `WHERE` on `e.valid_from` / `e.valid_to` is applied inside the traversal at each "
     "hop, so invalid branches are pruned instead of enumerated and filtered afterwards (docs/PERF.md)."),
    ("`CALL {}` subqueries", r"\bCALL \{",
     "Per-candidate shortest paths, and the level-by-level breadth-first closures for blast radius and storms."),
    ("`MERGE` idempotency (+ `ON CREATE SET`)", r"\bMERGE\b",
     "Stable ids make seeding, recall, hypotheses and evidence safe to repeat; no uniqueness constraints needed."),
    ("`FOREACH` conditional writes", r"\bFOREACH\b",
     "One round trip writes `SUPPORTS` or `REFUTES` (or confirms a hypothesis) depending on a parameter."),
    ("Pattern comprehensions", r"\[\(",
     "Counts evidence (ownership, authored changes, pages) per person inside one query."),
    ("`UNWIND $rows` batches", r"UNWIND \$rows",
     "One statement per batch instead of one per row."),
]


def kind(cypher: str) -> str:
    """W if the statement writes, else RO. Comment lines and string literals are ignored."""
    code = "\n".join(ln for ln in cypher.splitlines() if not ln.lstrip().startswith("//"))
    code = re.sub(r"//.*", "", _STRING.sub("''", code))
    return "W" if _WRITE.search(code) else "RO"


class _Refs(ast.NodeVisitor):
    """Collects repo.read("name") / repo.write("name") calls with the function they sit in."""

    def __init__(self, module: str, found: dict[str, set[tuple[str, str]]]):
        self.module, self.found, self.fn = module, found, ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        outer, self.fn = self.fn, node.name
        self.generic_visit(node)
        self.fn = outer

    def visit_Call(self, node: ast.Call) -> None:
        f, a = node.func, node.args
        if (isinstance(f, ast.Attribute) and f.attr in ("read", "write") and a
                and isinstance(a[0], ast.Constant) and isinstance(a[0].value, str)):
            self.found[a[0].value].add((f"{self.module}.{self.fn}" if self.fn else self.module, f.attr))
        self.generic_visit(node)


def references() -> dict[str, set[tuple[str, str]]]:
    found: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for base, rel in ((ROOT / "src", ROOT / "src"), (ROOT / "scripts", ROOT)):
        for f in sorted(base.rglob("*.py")):
            _Refs(".".join(f.relative_to(rel).with_suffix("").parts), found).visit(ast.parse(f.read_text()))
    for name, _ in INGEST:  # seeding passes the name as a variable
        found[name].add(("oncall_brain.services.seeding.seed", "write, via INGEST"))
    return found


def _cell(s: str) -> str:
    return s.replace("|", "\\|")


def render() -> str:
    qs = all_queries()
    refs = references()
    kinds = {n: kind(q.cypher) for n, q in qs.items()}
    bad = sorted(n for n in qs if kinds[n] == "W" and any(how == "read" for _, how in refs[n]))
    if bad:
        raise SystemExit(f"write statements called via repo.read (GRAPH.RO_QUERY rejects them): {bad}")
    files = sorted({q.file for q in qs.values()}, key=lambda f: (list(INTROS).index(f) if f in INTROS else 99, f))
    by_file = {f: [q for q in qs.values() if q.file == f] for f in files}
    ordered = [q for f in files for q in by_file[f]]
    ro = [n for n in qs if kinds[n] == "RO"]

    out = ["# Cypher query catalogue", "",
           "Generated by scripts/gen_queries_doc.py — do not edit by hand.", "",
           f"Every query the product runs: {len(qs)} named, parameterised statements in "
           "`src/oncall_brain/adapters/falkordb/queries/*.cypher`. Code refers to them by name only "
           "(`repo.read(\"name\", ...)` / `repo.write(\"name\", ...)`); user input never becomes Cypher text. "
           "**RO** statements run through `GRAPH.RO_QUERY`, so the database itself rejects a write; "
           "**W** statements may write. Regenerate with `make docs`.", "",
           "## Summary", "", "| Query | Kind | File | Purpose |", "|---|---|---|---|"]
    for q in ordered:
        out.append(f"| [{q.name}](#{q.name}) | {kinds[q.name]} | {q.file} | {_cell(q.purpose)} |")

    out += ["", "## Graph features this product depends on", "",
            "| Capability | Where | Why |", "|---|---|---|"]
    for cap, rx, why in CYPHER_FEATURES:
        hits = [q.name for q in ordered if re.search(rx, q.cypher) and q.file != "reference.cypher"]
        if hits:
            out.append(f"| {cap} | {', '.join(f'[{n}](#{n})' for n in hits)} | {why} |")
    out += [
        f"| `GRAPH.RO_QUERY` read-only guard | `FalkorRepository.read` in `adapters/falkordb/repository.py`; "
        f"{len(ro)} of {len(qs)} statements are RO | A read tool cannot mutate the graph even if its Cypher were "
        "wrong; the agent's writes go through a few narrow, named write statements. |",
        f"| `GRAPH.COPY` for resets | `FalkorGraphStore.snapshot` / `restore`, called by `services/seeding.py` "
        f"| Seeding keeps a `{PRISTINE}<tenant>` copy; a demo reset is a server-side graph copy, not a re-seed. |",
        f"| One graph per tenant | `FalkorGraphStore.tenant` -> graph `{PREFIX}<tenant>` | Tenants are isolated "
        "graphs in one FalkorDB, so memory and incidents never leak across tenants. |",
        f"| Indexes on `:Label(id)` | `FalkorRepository.ensure_schema`: {', '.join(INDEXED_LABELS)} | Every "
        "`MERGE` and lookup starts from an id, so each is an index seek before the traversal begins. |",
        f"| Range indexes on `.at` | `FalkorRepository.ensure_schema`: {', '.join(TIME_INDEXED)} | The alert-window "
        "filters (`recent_changes`, `anomalies_between`) are index scans, not label scans. |",
    ]

    for f in files:
        out += ["", f"## {f}", "", INTROS.get(f, f"Statements in `{f}`.")]
        for q in by_file[f]:
            used = ", ".join(f"`{m}` ({how})" for m, how in sorted(refs[q.name])) or "nothing in src/ or scripts/"
            body = "\n".join(ln for ln in q.cypher.splitlines() if not ln.startswith("// purpose:")).strip()
            out += ["", f"### {q.name}", "", f"**{kinds[q.name]}** · `{f}` · used by {used}", "",
                    q.purpose, "", "```cypher", body, "```"]
    return "\n".join(out) + "\n"


def main() -> None:
    text = render()
    if "--check" in sys.argv[1:]:
        if not OUT.exists() or OUT.read_text() != text:
            sys.exit("docs/QUERIES.md is stale: run `make docs`")
        print("docs/QUERIES.md is up to date")
        return
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(all_queries())} queries)")


if __name__ == "__main__":
    main()
