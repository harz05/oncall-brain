"""Loads named Cypher statements from queries/*.cypher.

A file holds one or more statements, each introduced by a header:
    // name: blast_radius
    // purpose: one line shown in docs/QUERIES.md
Statements are always run with parameters; user input is never formatted into Cypher text.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

QUERY_DIR = Path(__file__).parent / "queries"
_HEADER = re.compile(r"^// name: (\w+)\s*$", re.M)


@dataclass(frozen=True)
class NamedQuery:
    name: str
    purpose: str
    cypher: str
    file: str


def _parse(path: Path) -> list[NamedQuery]:
    text = path.read_text()
    starts = [m.start() for m in _HEADER.finditer(text)] + [len(text)]
    out = []
    for a, b in zip(starts, starts[1:], strict=False):
        block = text[a:b].strip()
        name = _HEADER.match(block).group(1)
        purpose = next((ln[len("// purpose:"):].strip() for ln in block.splitlines()
                        if ln.startswith("// purpose:")), "")
        cypher = "\n".join(ln for ln in block.splitlines() if not ln.startswith("// name:")).strip()
        out.append(NamedQuery(name, purpose, cypher, path.name))
    return out


@lru_cache
def all_queries() -> dict[str, NamedQuery]:
    queries: dict[str, NamedQuery] = {}
    for path in sorted(QUERY_DIR.glob("*.cypher")):
        for q in _parse(path):
            if q.name in queries:
                raise ValueError(f"duplicate query name {q.name!r} in {path.name}")
            queries[q.name] = q
    return queries


def get(name: str) -> NamedQuery:
    try:
        return all_queries()[name]
    except KeyError:
        raise KeyError(f"unknown query {name!r}; add it to adapters/falkordb/queries/") from None
