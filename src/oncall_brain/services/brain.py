"""Company brain: answer a free-form question from the graph first, then from the docs, tickets and chat in it.

1. Entity linking (link_entities): the services, teams, people, changes and tickets the question names.
2. Intent routing by plain keyword rules (INTENTS, first match wins), answered from edges about the linked entities:
   owner -> OWNS, members, ON_CALL, who_knows; expert -> who_knows; why -> DECIDES / SUPERSEDES decision records and
   change_story; how -> Runbook FOR_SERVICE, runbook pages, incidents FIXED_WITH; happened -> incidents IMPACTS /
   CAUSED_BY. No intent, or nothing linked of the kind it needs: the full-text answer alone.
3. FalkorDB's full-text indexes find the supporting docs, tickets and chat; on equal coverage of the question, those
   that MENTION (DECIDE, REQUESTED, were AUTHORED_BY) a linked entity or a person the fact named go first. The
   graph around them (MENTIONS, AUTHORED_BY, DECIDES, SUPERSEDES, REQUESTED, CITES, HAS_UPDATE, a change's CHANGED
   service, a service's OWNS team) names what they concern and flags docs a newer one superseded.
The answer leads with the graph fact, then quotes the supporting source; no LLM, so every claim points at a node."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from oncall_brain.agents.registry import ToolContext, tool
from oncall_brain.domain.models import Highlight, QueryRun, ToolOutput

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
# Intent rules on the lowered question, first match wins: "who owns kafka and who knows it" is about ownership.
INTENTS = (
    ("owner", re.compile(r"\bown(s|ed|er|ers)?\b|\bwhose\b|\bwhich team\b|\bon[ -]call\b")),
    ("expert", re.compile(r"\bwho knows\b|\bexperts?\b|\bask\b")),
    ("why", re.compile(r"\bwhy\b|\bdecid|\bdecision")),
    ("how", re.compile(r"\bhow (do|can|should|to)\b|\broll ?back|\brevert|\bfix|\brunbook")),
    ("happened", re.compile(r"\bwhat happened\b|\bincident|\boutage")),
)
# Same words, two entities (service and team 'checkout'): keep the more specific one; the team comes via OWNS.
KIND_RANK = {"change": 0, "ticket": 1, "service": 2, "person": 3, "team": 4}


class AskArgs(BaseModel):
    question: str = Field(max_length=300, description="A question in plain words, e.g. who owns kafka? why was "
                          "legacy-billing retired? how do I roll back a bad deploy on cart?")
    at: int | None = Field(None, description="Epoch seconds for 'who is on call'; default: the latest alert in the "
                           "graph")


def terms(question: str) -> list[str]:
    """Content words in order, at most 12. Only [a-z0-9] survives, so nothing reaches the index's query syntax."""
    words = re.findall(r"[a-z0-9]+", question.lower())
    return list(dict.fromkeys(w for w in words if len(w) > 1 and w not in STOPWORDS))[:12]


def padded(question: str) -> str:
    """The lowered question as space-separated tokens (a hyphen or colon inside one is kept: payments-gw, chg:x),
    padded with a space each side, so a name links only as whole words."""
    return f" {' '.join(re.findall(r'[a-z0-9]+(?:[:-][a-z0-9]+)*', question.lower()))} "


def link(rows: list[dict], q: str) -> list[dict]:
    """Longest match wins: a match inside a longer one is dropped (a first name inside a full name already linked);
    on the same words the more specific kind wins. In question order."""
    taken: list[tuple[int, int]] = []
    out = []
    for r in sorted(rows, key=lambda r: (-len(r["matched"]), KIND_RANK[r["kind"]])):
        a = q.find(f" {r['matched']} ") + 1
        b = a + len(r["matched"])
        if all(b <= x or a >= y for x, y in taken):
            taken.append((a, b))
            out.append((a, r))
    return [r for _, r in sorted(out, key=lambda x: x[0])]


def intent_of(question: str) -> str | None:
    q = question.lower()
    return next((name for name, rule in INTENTS if rule.search(q)), None)


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


@dataclass
class _Answer:
    """What an answer is built from: the graph-fact sentences, the ids they cite, the people they name (docs those
    people wrote are boosted as support), edges and nodes to light up, and every query run."""

    parts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list)
    related: dict[str, dict] = field(default_factory=dict)
    queries: list[QueryRun] = field(default_factory=list)

    def read(self, ctx: ToolContext, name: str, **params) -> list[dict]:
        q = ctx.repo.read(name, **params)
        self.queries.append(q)
        return q.rows

    def link(self, src: str, rel: str, dst: str, node: str, kind: str, name: str | None) -> None:
        self.edges.append((src, dst, rel))
        self.related.setdefault(node, {"id": node, "kind": kind, "name": name, "via": f"{src} {rel} {dst}"})


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}" if n else ""


def _of(ents: list[dict], *kinds: str) -> list[dict]:
    return [e for e in ents if e["kind"] in kinds]


def _experts(ctx: ToolContext, ans: _Answer, svc: dict) -> None:
    rows = ans.read(ctx, "who_knows", service=svc["id"])[:3]
    ans.people += [r["person"] for r in rows]
    for r in rows:
        ans.related.setdefault(r["person"], {"id": r["person"], "kind": "person", "name": r["name"],
                                             "via": f"who_knows {svc['id']} (score {r['score']})"})
    why = [", ".join(x for x in ("owning team" if r["on_owning_team"] else "", _n(r["changes"], "change"),
                                 _n(r["incidents"], "incident") + " paged for" if r["incidents"] else "",
                                 _n(r["docs"], "doc")) if x) for r in rows]
    ans.parts.append(f"People who know {svc['name']}: " + "; ".join(
        f"{r['name']} ({r['team']}, score {r['score']}: {w})" for r, w in zip(rows, why, strict=True)) + "."
                     if rows else f"Nobody on record knows {svc['name']}.")


def _owner(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    ids = {e["id"] for e in _of(ents, "service", "team")}
    if not ids:
        return
    rows = ans.read(ctx, "ownership", ids=sorted(ids), at=at)
    for team in dict.fromkeys(r["team"] for r in rows):
        rs = [r for r in rows if r["team"] == team]
        r = rs[0]
        named = [x["service_name"] for x in rs if x["service"] in ids or team in ids]
        svcs = ", ".join(named)
        for x in rs:
            ans.link(team, "OWNS", x["service"], team, "team", r["team_name"])
        when = {"given": f"at {_ts(r['at'])}", "latest alert": f"as of the latest alert in the graph ({_ts(r['at'])})",
                "clock": "now"}[r["clock"]]
        duty = f"nobody is on call {when}"
        if r["on_call"]:
            ans.link(r["on_call"], "ON_CALL", team, r["on_call"], "person", r["on_call_name"])
            duty = f"{r['on_call_name']} ({r['handle']}) is on call {when}"
        head = (f"{r['team_name']} owns {svcs}" if team in ids else
                f"{svcs} {'is' if len(named) == 1 else 'are'} owned by {r['team_name']}")
        ans.people += [m["id"] for m in r["members"]]
        ans.parts.append(f"{head}; {duty}; members: {', '.join(sorted(m['name'] for m in r['members']))}.")
    for svc in _of(ents, "service")[:1]:
        _experts(ctx, ans, svc)


def _expert(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    for svc in _of(ents, "service")[:2]:
        _experts(ctx, ans, svc)


def _why(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    if svcs := _of(ents, "service"):
        rows = ans.read(ctx, "decisions_about", ids=[s["id"] for s in svcs])
        # The current decision that covers the question best; the one it replaces is named and flagged.
        current = sorted((r for r in rows if not r["superseded_by"]),
                         key=lambda r: (-coverage(words, f"{r['title']} {r['text']}"), -(r["at"] or 0)))
        if current:
            d = current[0]
            ans.sources.append(d["id"])
            ans.edges.append((d["id"], d["service"], "DECIDES"))
            text = (f"The decision of record for {d['service_name']} is '{d['title']}' ({KINDS[d['kind']]}"
                    f"{', by ' + d['author'] if d['author'] else ''}, {_day(d['at'])}), current")
            if d["replaces"]:
                ans.link(d["id"], "SUPERSEDES", d["replaces"], d["replaces"], "doc", d["replaces_title"])
                text += f"; it supersedes '{d['replaces_title']}'"
            ans.parts.append(text + ".")
    for c in _of(ents, "change")[:2]:
        rows = ans.read(ctx, "change_story", change_id=c["id"])
        if not rows:
            continue
        r = rows[0]
        srcs = [s for s in r["sources"] if s.get("id")]
        docs, tickets = [s for s in srcs if s["kind"] == "Doc"], [s for s in srcs if s["kind"] == "Ticket"]
        ans.sources += [s["id"] for s in docs + tickets]
        ans.edges += [(c["id"], r["service"], "CHANGED")] + [(s["id"], c["id"], "MENTIONS") for s in docs] + [
            (s["id"], c["id"], "REQUESTED") for s in tickets] + [(i, c["id"], "CAUSED_BY") for i in r["incidents"]]
        if r["author_id"]:
            ans.link(c["id"], "AUTHORED_BY", r["author_id"], r["author_id"], "person", r["author"])
        ans.parts.append(
            f"{c['id']} ({r['kind']} on {r['service'].removeprefix('svc:')}: '{r['summary']}') was made by "
            f"{r['author'] or 'an unknown author'}{' (' + r['team'] + ')' if r['team'] else ''}"
            + (f", requested in {', '.join(s['title'] for s in tickets)}" if tickets else "")
            + (f", written up in {', '.join(repr(s['title']) for s in docs)}" if docs else "")
            + (f"; it caused {', '.join(r['incidents'])}" if r["incidents"] else "") + ".")


def _incident(r: dict) -> str:
    cause = (f"cause {r['cause']} ({r['cause_kind']} on {r['cause_service_name']})" if r["cause"]
             else "cause not confirmed")
    fix = f", fixed with '{r['runbook_title']}'" if r["runbook"] else ""
    return f"{r['id']} '{r['title']}' ({_day(r['at'])}, {r['status']}; {cause}{fix})"


def _incidents(ans: _Answer, rows: list[dict]) -> str:
    """Cite and light up the incidents an answer names; their one-line descriptions."""
    for r in rows:
        ans.sources.append(r["id"])
        for s in r["impacts"]:
            ans.link(r["id"], "IMPACTS", s, r["id"], "incident", r["title"])
        if r["cause"]:
            ans.link(r["id"], "CAUSED_BY", r["cause"], r["cause"], "change",
                     f"{r['cause_kind']} on {r['cause_service_name']}")
            ans.link(r["cause"], "CHANGED", r["cause_service"], r["cause_service"], "service",
                     r["cause_service_name"])
        if r["runbook"]:
            ans.link(r["id"], "FIXED_WITH", r["runbook"], r["runbook"], "runbook", r["runbook_title"])
    return "; ".join(map(_incident, rows))


def _how(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    if not (svcs := _of(ents, "service")):
        return
    ids, names = [s["id"] for s in svcs], ", ".join(s["name"] for s in svcs)
    rows = ans.read(ctx, "service_runbooks", ids=ids)
    runbooks = sorted({r["id"]: r for r in rows if r["source"] == "runbook"}.values(), key=lambda r: -r["successes"])
    for r in runbooks[:2]:
        ans.sources.append(r["id"])
        ans.edges.append((r["id"], r["service"], "FOR_SERVICE"))
        ans.parts.append(f"Runbook for {r['service_name']}: '{r['title']}' ({r['id']}, worked {r['successes']} of "
                         f"{r['uses']} times): {'; '.join(r['steps'])}.")
    fixed = [r for r in ans.read(ctx, "service_incidents", ids=ids) if r["runbook"]][:2]
    if fixed:
        ans.parts.append(f"Past fixes: {_incidents(ans, fixed)}.")
    if not runbooks and not fixed:
        ans.parts.append(f"No runbook for {names} on record: no Runbook is FOR_SERVICE it and no past incident on it "
                         "was FIXED_WITH one.")
    # Pages, this service's and the general ones, ranked by how much of the question they cover.
    pages = sorted({r["id"]: r for r in rows if r["source"] != "runbook"}.values(),
                   key=lambda r: (-coverage(words, f"{r['title']} {r['text']}"), r["source"] == "general"))
    if pages:
        p = pages[0]
        ans.sources.append(p["id"])
        if p["service"]:
            ans.edges.append((p["id"], p["service"], "MENTIONS"))
        scope = "general, for any service" if p["source"] == "general" else f"mentions {p['service_name']}"
        ans.parts.append(f"Best runbook page: '{p['title']}' ({p['id']}, {scope}"
                         f"{', by ' + p['author'] if p['author'] else ''}).")
        others = [r["title"] for r in pages[1:] if r["source"] == "page"][:2]
        if others:
            ans.parts.append(f"Other runbook pages that mention {names}: " + ", ".join(map(repr, others)) + ".")


def _happened(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    if not (xs := _of(ents, "service", "change")):
        return
    names = ", ".join(e["name"] if e["kind"] == "service" else e["id"] for e in xs)
    rows = ans.read(ctx, "service_incidents", ids=[e["id"] for e in xs])[:3]
    ans.parts.append(f"Incidents on {names}, newest first: {_incidents(ans, rows)}." if rows
                     else f"No incidents on record for {names}.")


ROUTES = {"owner": _owner, "expert": _expert, "why": _why, "how": _how, "happened": _happened}


def _ts(at: int) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M UTC")


@tool()
def ask(ctx: ToolContext, a: AskArgs) -> ToolOutput:
    """Company brain: answer a free-form question from the graph, then from docs (postmortems, design notes,
    decision records, runbook pages), tickets and chat. Links the services, teams, people, changes and tickets the
    question names; by intent answers from the graph first (who owns -> OWNS + on call; who knows -> expertise
    ranking; why -> decisions of record + change story; how do I -> runbooks + past fixes; what happened ->
    incidents), then full-text search finds supporting sources, preferring those tied to a linked entity, flags
    docs a newer doc superseded, and lists every source."""
    words = terms(a.question)
    empty = {"hits": [], "related": [], "sources": [], "linked": [], "intent": None}
    if not words:
        return ToolOutput(summary="Nothing to search for", data={**empty, "answer": "Ask with a few content words "
                          "(a service, what happened); one-letter words and words like 'why' or 'the' match nothing."})
    ans = _Answer()
    q = padded(a.question)
    ents = link(ans.read(ctx, "link_entities", q=q), q)
    intent = intent_of(a.question)
    if intent and ents:
        ROUTES[intent](ctx, ans, ents, words, a.at)
    lead = list(ans.sources)  # what the graph fact cites: those docs lead the hits
    boost = {e["id"] for e in ents} | set(ans.people)
    rows = ans.read(ctx, "search_knowledge", query="|".join(words), limit=PER_LABEL)
    rows = list({r["id"]: r for r in rows}.values())  # a doc superseded twice comes back twice
    for r in rows:
        r["matched"] = coverage(words, f"{r['title']} {r['text']}")
        r["links"] = sorted(boost & {r["id"], *r["refs"]})
    # Docs the graph fact cites first. Then coverage (the index's own score favours short chat that repeats one word);
    # on equal coverage, the hits that are or MENTION more linked entities, or were written by people the fact named
    # (a tie-break, not a bonus: the entity's name already counts in coverage). A superseded doc goes below the doc
    # that replaced it, so what is current comes first; then a title on the topic beats a passing mention.
    ranked = sorted(rows, key=lambda r: (lead.index(r["id"]) if r["id"] in lead else len(lead), -r["matched"],
                                            -len(r["links"]), r["superseded_by"] is not None,
                                            -coverage(words, r["title"] or ""), LABEL_ORDER[r["label"]], -r["score"],
                                            -(r["at"] or 0)))[:TOP]
    # intent: the route whose graph fact leads the answer; "search" when none did (no rule, or nothing linked).
    info = {"linked": [{k: e[k] for k in ("id", "kind", "name", "matched")} for e in ents],
            "intent": intent if ans.parts else "search"}
    if not ranked and not ans.parts:
        return ToolOutput(summary=f"No docs, tickets or chat mention {', '.join(words)}", queries=ans.queries,
                          data={**empty, **info, "answer": f"Nothing in docs, tickets or chat mentions "
                                f"{', '.join(words)}."})
    by_hit: dict[str, list[dict]] = {h["id"]: [] for h in ranked}
    context = ans.read(ctx, "knowledge_context", ids=list(by_hit)) if ranked else []
    for r in sorted(context, key=lambda r: list(by_hit).index(r["hit"])):  # "via" names the most relevant hit
        by_hit[r["hit"]].append(r)
        src, dst = (r["hit"], r["id"]) if r["outgoing"] else (r["id"], r["hit"])
        ans.link(src, r["rel"], dst, r["id"], r["label"].lower(), r["name"])
        if r["author"]:
            ans.link(r["id"], "AUTHORED_BY", r["author"], r["author"], "person", r["author_name"])
        if r["service"]:
            ans.link(r["id"], "CHANGED", r["service"], r["service"], "service", r["service_name"])
        if r["team"]:
            ans.link(r["team"], "OWNS", r["id"], r["team"], "team", r["team_name"])
    parts = ans.parts + _support(words, ranked, lead) if ans.parts else _from_docs(words, ranked, by_hit)
    hits = [{"id": h["id"], "kind": h["kind"], "title": h["title"], "snippet": snippet(words, h["text"]),
             "score": round(h["score"], 2), "matched": h["matched"], "author": h["author"], "at": h["at"],
             "superseded_by": h["superseded_by"], "links": h["links"]} for h in ranked]
    sources = list(dict.fromkeys(lead + [h["id"] for h in ranked]))
    related = {k: v for k, v in ans.related.items() if k not in sources}
    flags = sum(h["superseded_by"] is not None for h in ranked)
    what = (f"{intent}: {', '.join(e['matched'] for e in ents)}" if ans.parts else f"'{' '.join(words)}'") + (
        f"; most relevant {ranked[0]['id']}" if ranked else "")
    return ToolOutput(summary=f"{len(sources)} sources for {what}" + (f" ({flags} superseded)" if flags else ""),
                      data={"answer": " ".join(parts), "hits": hits, "related": list(related.values()),
                            "sources": sources, **info},
                      queries=ans.queries, highlight=Highlight(
                          nodes=list(dict.fromkeys(sources + list(related) + [e["id"] for e in ents])),
                          edges=list(dict.fromkeys(ans.edges))))


def _support(words: list[str], ranked: list[dict], lead: list[str]) -> list[str]:
    """After a graph fact: quote the best source (by name if the fact already cited it), then the next two."""
    if not ranked:
        return [f"No docs, tickets or chat mention {', '.join(words)}."]
    top = ranked[0]
    quote = snippet(words, top["text"])
    parts = [f"'{top['title']}' says: \"{quote}\"" if top["id"] in lead else
             f"Most relevant: {_describe(top)}: \"{quote}\""]
    if top["superseded_by"]:
        parts.append(f"Superseded by '{top['superseded_title']}' ({top['superseded_by']}).")
    if len(ranked) > 1:
        parts.append("Also: " + "; ".join(_describe(h) for h in ranked[1:3]) + ".")
    return parts


def _from_docs(words: list[str], ranked: list[dict], by_hit: dict[str, list[dict]]) -> list[str]:
    """No graph fact to lead with: the answer is the best sources and what the graph says about them."""
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
    return parts
