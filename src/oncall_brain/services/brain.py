"""Company brain: answer a free-form question from the docs, tickets and chat in the graph, with its sources.

FalkorDB's full-text indexes find the sources; the graph around them (MENTIONS, AUTHORED_BY, DECIDES, SUPERSEDES,
REQUESTED, CITES, HAS_UPDATE, then a change's CHANGED service and a service's OWNS team) says which services, changes,
incidents and people they concern and whether a doc is still current. The answer is assembled from those facts, no LLM,
so every claim in it points at a node."""

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from oncall_brain.agents.registry import ToolContext, tool
from oncall_brain.domain.models import Highlight, ToolOutput

# Question words carry no content and the index has no stopword list, so they would match nearly everything.
STOPWORDS = frozenset(
    "a about after all also an and any are as ask at be been before but by can could did do does for from had has have "
    "how i if in into is it its know knows me my no not of on or our should so tell than that the their them then "
    "there these they this those to us was we were what when where which who whom whose why will with would you your"
    .split())
LABEL_ORDER = {"Doc": 0, "Ticket": 1, "Message": 2}  # equal coverage: the considered record before the chatter
KINDS = {"postmortem": "postmortem", "design": "design note", "decision": "decision record", "runbook": "runbook page",
         "ticket": "ticket", "chat": "chat", "status_update": "status update"}
TOP, PER_LABEL = 5, 30


class AskArgs(BaseModel):
    question: str = Field(max_length=300, description="A question in plain words, e.g. why was the payments-gw pool "
                          "lowered? or who designed the checkout retries?")


def terms(question: str) -> list[str]:
    """Content words in order, at most 12. Only [a-z0-9] survives, so nothing reaches the index's query syntax."""
    words = re.findall(r"[a-z0-9]+", question.lower())
    return list(dict.fromkeys(w for w in words if len(w) > 1 and w not in STOPWORDS))[:12]


def _stem(word: str) -> str:
    # ponytail: prefix stem ("lowered" ~ "lower", "designed" ~ "design"); swap in a real stemmer if it misfires.
    return word[:max(4, len(word) - 2)]


def coverage(words: list[str], text: str) -> int:
    """How many of the question's words the text contains (stem match)."""
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return sum(any(t.startswith(_stem(w)) for t in tokens) for w in words)


def snippet(words: list[str], text: str, width: int = 240) -> str:
    """The sentence (or line) that covers most of the question, plus the one after it (the reason often follows)."""
    sents = re.split(r"(?<=[.!?])\s+|\s*\n\s*", (text or "").strip())
    best = max(range(len(sents)), key=lambda i: (coverage(words, sents[i]), -i))
    out = " ".join(sents[best:best + 2])
    return out if len(out) <= width else out[:width - 3].rstrip() + "..."


def _day(at: int | None) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d") if at else "undated"


def _describe(h: dict) -> str:
    name = h["title"] if h["label"] != "Message" else f'"{snippet([], h["text"], 90)}"'
    what = KINDS.get(h["kind"], h["kind"] or "") + (f" in {h['title']}" if h["label"] == "Message" else "")
    return f"{name} ({what}{', by ' + h['author'] if h['author'] else ''}, {_day(h['at'])})"


def _first(xs: list[str], n: int) -> list[str]:
    return list(dict.fromkeys(x for x in xs if x))[:n]


@tool()
def ask(ctx: ToolContext, a: AskArgs) -> ToolOutput:
    """Company brain: answer a free-form question from docs (postmortems, design notes, decision records, runbook
    pages), tickets and chat. Full-text search finds the sources, ranked by how many of the question's words each
    contains; the graph around them names the services, changes and people involved and flags docs that a newer doc
    superseded. Every answer lists its sources."""
    words = terms(a.question)
    empty = {"hits": [], "related": [], "sources": []}
    if not words:
        return ToolOutput(summary="Nothing to search for", data={**empty, "answer": "Ask with a few content words "
                          "(a service, what happened); one-letter words and words like 'why' or 'the' match nothing."})
    sq = ctx.repo.read("search_knowledge", query="|".join(words), limit=PER_LABEL)
    rows = list({r["id"]: r for r in sq.rows}.values())  # a doc superseded twice comes back twice
    for r in rows:
        r["matched"] = coverage(words, f"{r['title']} {r['text']}")
    # Coverage first: the index's own score favours short chat that repeats one word. A superseded doc goes below
    # the doc that replaced it, so what is current comes first; then a title on the topic beats a passing mention.
    ranked = sorted(rows, key=lambda r: (-r["matched"], r["superseded_by"] is not None,
                                            -coverage(words, r["title"] or ""), LABEL_ORDER[r["label"]], -r["score"],
                                            -(r["at"] or 0)))[:TOP]
    if not ranked:
        return ToolOutput(summary=f"No docs, tickets or chat mention {', '.join(words)}", queries=[sq],
                          data={**empty, "answer": f"Nothing in docs, tickets or chat mentions {', '.join(words)}."})
    cq = ctx.repo.read("knowledge_context", ids=[h["id"] for h in ranked])

    related: dict[str, dict] = {}
    edges: list[tuple[str, str, str]] = []

    def link(src: str, rel: str, dst: str, node: str, label: str, name: str | None) -> None:
        edges.append((src, dst, rel))
        related.setdefault(node, {"id": node, "kind": label.lower(), "name": name, "via": f"{src} {rel} {dst}"})

    by_hit: dict[str, list[dict]] = {h["id"]: [] for h in ranked}
    for r in sorted(cq.rows, key=lambda r: list(by_hit).index(r["hit"])):  # "via" names the most relevant hit
        by_hit[r["hit"]].append(r)
        src, dst = (r["hit"], r["id"]) if r["outgoing"] else (r["id"], r["hit"])
        link(src, r["rel"], dst, r["id"], r["label"], r["name"])
        if r["author"]:
            link(r["id"], "AUTHORED_BY", r["author"], r["author"], "Person", r["author_name"])
        if r["service"]:
            link(r["id"], "CHANGED", r["service"], r["service"], "Service", r["service_name"])
        if r["team"]:
            link(r["team"], "OWNS", r["id"], r["team"], "Team", r["team_name"])
    hit_ids = {h["id"] for h in ranked}
    related = {k: v for k, v in related.items() if k not in hit_ids}

    # Facts come from the hits that cover the question best (up to 3), most relevant first; weaker hits only
    # contribute people and the "Also" line, so a passing mention does not drag in unrelated changes.
    lead = [h for h in ranked if h["matched"] == ranked[0]["matched"]][:3]
    out = [r for h in lead for r in by_hit[h["id"]] if r["outgoing"]]
    services = _first([r["name"] for r in out if r["label"] == "Service"] + [r["service_name"] for r in out], 4)
    changes = _first([f"{r['id']} '{r['name']}'" for r in out if r["label"] == "Change"], 2)
    incidents = _first([f"{r['id']} '{r['name']}'" for h in lead for r in by_hit[h["id"]] if r["label"] == "Incident"],
                       2)  # either way: a postmortem MENTIONS its incident, an incident HAS_UPDATE its status update
    people = _first([ranked[0]["author"]] + [r["author_name"] for r in out if r["label"] == "Change"]
                    + [h["author"] for h in ranked[1:]], 3)
    top, top_rows = ranked[0], by_hit[ranked[0]["id"]]
    parts = [f"Most relevant: {_describe(top)}: \"{snippet(words, top['text'])}\""]
    facts = ([f"it concerns {', '.join(services)}"] if services else []) + (
        [f"related changes: {', '.join(changes)}"] if changes else []) + (
        [f"incidents: {', '.join(incidents)}"] if incidents else []) + (
        [f"people who know: {', '.join(people)}"] if people else [])
    if facts:
        line = "; ".join(facts)
        parts.append(line[0].upper() + line[1:] + ".")
    decides = _first([r["name"] for r in top_rows if r["rel"] == "DECIDES"], 3)
    if decides:
        parts.append(f"It is the decision of record for {', '.join(decides)}.")
    for r in top_rows:
        if r["rel"] == "SUPERSEDES" and r["outgoing"]:
            parts.append(f"It replaces '{r['name']}'" + (f" by {r['author_name']}." if r["author_name"] else "."))
    if top["superseded_by"]:
        parts.append(f"Superseded by '{top['superseded_title']}' ({top['superseded_by']}): read that for the "
                     "current state.")
    if len(ranked) > 1:
        parts.append("Also: " + "; ".join(_describe(h) for h in ranked[1:3]) + ".")

    hits = [{"id": h["id"], "kind": h["kind"], "title": h["title"], "snippet": snippet(words, h["text"]),
             "score": round(h["score"], 2), "matched": h["matched"], "author": h["author"], "at": h["at"],
             "superseded_by": h["superseded_by"]} for h in ranked]
    sources = [h["id"] for h in ranked]
    flags = sum(h["superseded_by"] is not None for h in ranked)
    return ToolOutput(summary=f"{len(ranked)} sources for '{' '.join(words)}'; most relevant {top['id']}"
                      + (f" ({flags} superseded)" if flags else ""),
                      data={"answer": " ".join(parts), "hits": hits, "related": list(related.values()),
                            "sources": sources},
                      queries=[sq, cq], highlight=Highlight(nodes=sources + list(related), edges=list(dict.fromkeys(
                          edges))))
