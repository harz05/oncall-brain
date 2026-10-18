"""Company brain: answer a free-form question from the graph first, then from the docs, tickets and chat in it.

1. Entity linking (link_entities): the services, teams, people, changes, tickets, incidents and initiatives the
   question names.
2. Intent routing by plain keyword rules (INTENTS, first match wins), answered from edges about the linked entities:
   owner -> OWNS valid at the time asked (a named incident's time, else the live edge, with the owners before and
   after), members, ON_CALL, who_knows; expert -> who_knows; why -> DECIDES / SUPERSEDES decision records and
   change_story; how -> Runbook FOR_SERVICE, runbook pages, incidents FIXED_WITH; happened -> incidents IMPACTS /
   CAUSED_BY; project / members -> an Initiative's DRIVES team, LEADS person, PART_OF tickets with their REQUESTED
   changes and the incidents those are blamed for, and the docs that MENTION it. No intent, or nothing linked of the
   kind it needs: the full-text answer alone (a linked initiative with no rule is answered as "project").
3. FalkorDB's full-text indexes find the supporting docs, tickets and chat; on equal coverage of the question, those
   that MENTION (DECIDE, REQUESTED, were AUTHORED_BY) a linked entity or a person the fact named go first. The
   graph around them (MENTIONS, AUTHORED_BY, DECIDES, SUPERSEDES, REQUESTED, CITES, HAS_UPDATE, a change's CHANGED
   service, a service's OWNS team) names what they concern and flags docs a newer one superseded.
The answer leads with the graph fact, then quotes the supporting source; no LLM, so every claim points at a node."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from oncall_brain.agents.registry import ToolContext, tool
from oncall_brain.domain.models import Highlight, QueryRun, ToolOutput
from oncall_brain.services import sessions

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
# "what did I ask about who owns kafka" is a recall: history comes first, since "ask" and "owns" would match below.
INTENTS = (
    ("history", re.compile(r"\bwhat (did|have) i ask|\bdid i ask\b|\bmy (last|previous|earlier|recent|past) "
                           r"questions?\b|\bwhat was i asking\b|\bmy questions\b")),
    ("owner", re.compile(r"\bown(s|ed|er|ers)?\b|\bwhose\b|\bwhich team\b|\bon[ -]call\b")),
    # After owner, so "who is on call" stays ownership; "who is on the Q4 cost review" is its people.
    ("members", re.compile(r"\bwho('s| is| are| was| were) (on|in|behind|working on|leading|driving|running)\b"
                           r"|\bwho (leads|drives|works on)\b")),
    ("project", re.compile(r"\bwhat('s| is| are| was| were) .*\b(changing|delivering|covering)\b|\binitiative"
                           r"|\bproject|\bprogramme?\b|\bwhen is .* due\b|\bdue (date|by|on|in)\b|\bdeadline")),
    ("expert", re.compile(r"\bwho knows\b|\bexperts?\b|\bask\b")),
    ("why", re.compile(r"\bwhy\b|\bdecid|\bdecision")),
    ("how", re.compile(r"\bhow (do|can|should|to)\b|\broll ?back|\brevert|\bfix|\brunbook")),
    ("happened", re.compile(r"\bwhat happened\b|\bincident|\boutage")),
)
# Same words, two entities (service and team 'checkout'): keep the more specific one; the team comes via OWNS.
KIND_RANK = {"change": 0, "ticket": 1, "incident": 2, "initiative": 3, "service": 4, "person": 5, "team": 6}


class AskArgs(BaseModel):
    question: str = Field(max_length=300, description="A question in plain words, e.g. who owns kafka? who owned "
                          "payments-gw at the time of inc:0911? why was legacy-billing retired? how do I roll back a "
                          "bad deploy on cart? what is the Q4 cost review changing and who is on it? As a follow-up: "
                          "and who is on call for it? To recall: what did I ask about payments-gw?")
    at: int | None = Field(None, description="Epoch seconds for 'who owned' and 'who was on call'; default: a "
                           "named incident's time for the owner, the latest alert in the graph for the rotation")
    user: str | None = Field(None, pattern=sessions.USER, description="Who is asking, e.g. person:hana-costa (a "
                             "Person id or @handle). The question is then remembered in that person's session in the "
                             "graph: a follow-up can say 'it' or 'them', and 'what did I ask about X' works. Without "
                             "it nothing is recorded")
    session: str = Field("default", pattern=sessions.KEY, description="Conversation key for the user, e.g. a chat or "
                         "terminal id; 'it' is read within one session. Default: one running conversation")

    @field_validator("user", "session", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> Any:
        return sessions.lower(v)


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
    why = [", ".join(x for x in ("owning team" if r["on_owning_team"] else "",
                                 "owned it before" if r["on_former_owning_team"] else "", _n(r["changes"], "change"),
                                 _n(r["incidents"], "incident") + " paged for" if r["incidents"] else "",
                                 _n(r["docs"], "doc")) if x) for r in rows]
    ans.parts.append(f"People who know {svc['name']}: " + "; ".join(
        f"{r['name']} ({r['team']}, score {r['score']}: {w})" for r, w in zip(rows, why, strict=True)) + "."
                     if rows else f"Nobody on record knows {svc['name']}.")


def _span(x: dict, name_it: bool) -> str:
    """One service's ownership history around the OWNS edge the answer used: the owner before it (the edge that ended
    when this one began) and the one after it (the edge that began when this one ended)."""
    out = []
    if x["before"]:
        b = max(x["before"], key=lambda e: e["until"])
        out.append(f"since {_ts(x['since'])}, before that {b['name']}")
    if x["after"]:
        n = min(x["after"], key=lambda e: e["from"])
        out.append(f"until {_ts(x['until'])}, then {n['name']}")
    return (f"{x['service_name']} " if name_it else "") + ", ".join(out) if out else ""


def _owner(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    ids = {e["id"] for e in _of(ents, "service", "team")}
    if not ids:
        return
    # "who owned payments-gw at the time of inc:0911": a named incident sets the time asked, unless one was given.
    inc = next((e for e in _of(ents, "incident") if e.get("at")), None)
    if at is None and inc:
        at = inc["at"]
    rows = ans.read(ctx, "ownership", ids=sorted(ids), at=at)
    for team in dict.fromkeys(r["team"] for r in rows):
        rs = [r for r in rows if r["team"] == team]
        r = rs[0]
        mine = [x for x in rs if x["service"] in ids or team in ids]
        named = [x["service_name"] for x in mine]
        svcs = ", ".join(named)
        for x in rs:
            ans.link(team, "OWNS", x["service"], team, "team", r["team_name"])
        past = r["clock"] == "given"  # a time was asked about: say it in the past tense, with the handovers around it
        when = {"given": f"at {_ts(r['at'])}", "latest alert": f"as of the latest alert in the graph ({_ts(r['at'])})",
                "clock": "now"}[r["clock"]]
        be = "was" if past else "is"
        duty = f"no on-call rotation is recorded {when}" if past else f"nobody is on call {when}"  # R36
        if r["on_call"]:
            ans.link(r["on_call"], "ON_CALL", team, r["on_call"], "person", r["on_call_name"])
            duty = f"{r['on_call_name']} ({r['handle']}) {be} on call {when}"
        one = len(named) == 1
        head = (f"{r['team_name']} {'owned' if past else 'owns'} {svcs}" if team in ids else
                f"{svcs} {('was' if one else 'were') if past else ('is' if one else 'are')} owned by {r['team_name']}")
        if past:
            head += f" {when}" + (f", the time of {inc['id']}" if inc and at == inc["at"] else "")
        if history := [h for h in (_span(x, len(mine) > 1) for x in mine) if h]:
            head += f" ({'; '.join(history)})"
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
    if not (xs := _of(ents, "service", "change", "incident")):
        return
    names = ", ".join(e["name"] if e["kind"] == "service" else e["id"] for e in xs)
    rows = ans.read(ctx, "service_incidents", ids=[e["id"] for e in xs])[:3]
    what = f"What happened in {names}" if all(e["kind"] == "incident" for e in xs) else f"Incidents on {names}"
    ans.parts.append(f"{what}, newest first: {_incidents(ans, rows)}." if rows
                     else f"No incidents on record for {names}.")


def _project(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None,
             who_first: bool = False) -> None:
    """An initiative as the graph has it: goal, the team driving and the person leading it, its tickets with the
    change each requested and the incidents that change is blamed for, who is on it (lead, filers, change authors),
    and the decision records and design notes that mention it (current ones first)."""
    if not (inits := _of(ents, "initiative")):
        return
    for r in ans.read(ctx, "initiative_story", ids=[e["id"] for e in inits])[:2]:
        people: dict[str, tuple[str, list[str]]] = {}
        if r["team"]:
            ans.link(r["team"], "DRIVES", r["id"], r["team"], "team", r["team_name"])
        if r["lead"]:
            ans.link(r["lead"], "LEADS", r["id"], r["lead"], "person", r["lead_name"])
            ans.people.append(r["lead"])
            people[r["lead"]] = (r["lead_name"], ["lead"])
        head = (f"'{r['name']}' is {r['status']}" + (f", driven by {r['team_name']}" if r["team"] else "")
                + (f", led by {r['lead_name']}" if r["lead"] else "") + (f", due {_day(r['due'])}" if r["due"] else "")
                + f": {r['goal']}")
        work = []
        for t in sorted(r["tickets"], key=lambda t: t["at"] or 0):
            ans.sources.append(t["id"])
            ans.edges.append((t["id"], r["id"], "PART_OF"))
            if t["by_id"]:
                ans.link(t["id"], "AUTHORED_BY", t["by_id"], t["by_id"], "person", t["by"])
                people.setdefault(t["by_id"], (t["by"], []))[1].append(f"filed {t['id'].removeprefix('ticket:')}")
            line = t["title"]
            if t["change"]:
                ans.link(t["id"], "REQUESTED", t["change"], t["change"], "change", t["summary"])
                ans.link(t["change"], "CHANGED", t["service"], t["service"], "service", t["service_name"])
                line += (f" -> {t['change']} ({t['kind']} on {t['service_name']}"
                         + (f" by {t['change_by']}" if t["change_by"] else "")
                         + (", rolled back" if t["rolled_back"] else "") + ")")
                if t["change_by_id"]:
                    people.setdefault(t["change_by_id"], (t["change_by"], []))[1].append(
                        f"made {t['change'].removeprefix('chg:')}")
                for inc in sorted(t["incidents"], key=lambda i: i["id"]):
                    if inc["status"] == "confirmed":
                        ans.link(inc["id"], "CAUSED_BY", t["change"], inc["id"], "incident", inc["title"])
                    else:
                        ans.related.setdefault(inc["id"], {"id": inc["id"], "kind": "incident", "name": inc["title"],
                                                           "via": f"{inc['id']} HAS_HYPOTHESIS SUSPECTS {t['change']}"})
                    line += f", {'caused' if inc['status'] == 'confirmed' else 'blamed for'} {inc['id']}"
            else:
                line += " (no change recorded)"
            work.append(line)
        docs = sorted((d for d in r["docs"] if d["kind"] in ("decision", "design")),
                      key=lambda d: (d["superseded_by"] is not None, -(d["at"] or 0)))
        for d in docs:
            ans.sources.append(d["id"])
            ans.edges.append((d["id"], r["id"], "MENTIONS"))
        on_it = "On it: " + ", ".join(f"{name} ({', '.join(roles)})" for name, roles in people.values()) + "." if (
            people) else "Nobody is recorded on it."
        doing = "Work: " + "; ".join(work) + "." if work else "No ticket is part of it yet."
        decided = ("Decisions: " + "; ".join(
            f"'{d['title']}' ({KINDS[d['kind']]}{', by ' + d['by'] if d['by'] else ''}, {_day(d['at'])}"
            + (f", superseded by {d['superseded_by']}" if d["superseded_by"] else "") + ")" for d in docs) + "."
            if docs else "")
        ans.parts += [p for p in ([head + ".", on_it, doing] if who_first else [head + ".", doing, on_it]) + [decided]
                      if p]


def _members(ctx: ToolContext, ans: _Answer, ents: list[dict], words: list[str], at: int | None) -> None:
    _project(ctx, ans, ents, words, at, who_first=True)


ROUTES = {"owner": _owner, "members": _members, "project": _project, "expert": _expert, "why": _why, "how": _how,
          "happened": _happened}


def _ts(at: int) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M UTC")


@tool()
def ask(ctx: ToolContext, a: AskArgs) -> ToolOutput:
    """Company brain: answer a free-form question from the graph, then from docs (postmortems, design notes,
    decision records, runbook pages), tickets and chat. Links the services, teams, people, changes, tickets and
    incidents the question names; by intent answers from the graph first (who owns -> OWNS + on call, at a named
    incident's time ("who owned payments-gw at the time of inc:0911"), with the owners before and after; who knows ->
    expertise
    ranking; why -> decisions of record + change story; how do I -> runbooks + past fixes; what happened ->
    incidents; what is X changing / who is on X -> an initiative's tickets, changes, people, blamed incidents and
    decisions), then full-text search finds supporting sources, preferring those tied to a linked entity, flags
    docs a newer doc superseded, and lists every source. Given a user, the question is remembered in that person's
    session in the graph: a follow-up can say "it" or "them" (read as what the previous question was about; the
    answer says so), and "what did I ask about payments-gw" lists their earlier questions with the sources cited."""
    empty = {"hits": [], "related": [], "sources": [], "linked": [], "intent": None, "resolved": None,
             "recorded": None}
    ans = _Answer()
    sid = sessions.session_id(a.user, a.session) if a.user else None
    # A follow-up's "it" means what the previous question in this session was about (session_context).
    previous = (ans.read(ctx, "session_context", session_id=sid) or [None])[0] if sid else None
    question, carried, pronoun = (sessions.resolve(a.question, previous["entities"]) if previous
                                  else (a.question, [], None))
    resolved = ({"pronoun": pronoun, "as": [e["id"] for e in carried],
                 "from": {"question": previous["question"], "seq": previous["seq"], "text": previous["text"]}}
                if carried else None)
    lead_in = (f'Taking "{pronoun}" as {" and ".join(sessions.mention(e) for e in carried)}, from your earlier '
               f'question "{previous["text"]}". ' if carried else "")
    words = terms(question)
    if not words:
        return ToolOutput(summary="Nothing to search for", queries=ans.queries, data={
            **empty, "resolved": resolved, "answer": lead_in + "Ask with a few content words (a service, what "
            "happened); one-letter words and words like 'why' or 'the' match nothing."})
    intent = intent_of(question)
    if intent == "history":
        return _history(ctx, ans, a, question, {**empty, "resolved": resolved})
    q = padded(question)
    ents = link(ans.read(ctx, "link_entities", q=q), q)
    asked = padded(a.question)
    for e in ents:  # carried: linked through the pronoun, not named in the question as it was asked
        e["carried"] = bool(carried) and e["id"] in resolved["as"] and f" {e['matched']} " not in asked
    if intent and ents:
        ROUTES[intent](ctx, ans, ents, words, a.at)
    elif _of(ents, "initiative"):  # no rule matched ("tell me about the Q4 cost review"): the initiative itself
        intent = "project"
        _project(ctx, ans, ents, words, a.at)
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
    info = {"linked": [{k: e[k] for k in ("id", "kind", "name", "matched", "carried")} for e in ents],
            "intent": intent if ans.parts else "search", "resolved": resolved, "recorded": None}
    if not ranked and not ans.parts:
        out = ToolOutput(summary=f"No docs, tickets or chat mention {', '.join(words)}", queries=ans.queries,
                         data={**empty, **info, "answer": lead_in + f"Nothing in docs, tickets or chat mentions "
                               f"{', '.join(words)}."})
        return _remember(ctx, a, sid, question if carried else None, out, ents, [])
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
    out = ToolOutput(summary=f"{len(sources)} sources for {what}" + (f" ({flags} superseded)" if flags else ""),
                     data={"answer": lead_in + " ".join(parts), "hits": hits, "related": list(related.values()),
                           "sources": sources, **info},
                     queries=ans.queries, highlight=Highlight(
                         nodes=list(dict.fromkeys(sources + list(related) + [e["id"] for e in ents])),
                         edges=list(dict.fromkeys(ans.edges))))
    return _remember(ctx, a, sid, question if carried else None, out, ents, sources)


def _remember(ctx: ToolContext, a: AskArgs, sid: str | None, resolved: str | None, out: ToolOutput,
              ents: list[dict], sources: list[str]) -> ToolOutput:
    """Given a user: append the question to their session in the graph (sessions.record), say so in the data and
    keep the write in the trace. ABOUT the linked entities, ANSWERED_WITH the sources in rank order."""
    if not sid:
        return out
    about = [{"id": e["id"], "matched": e["matched"], "carried": e["carried"]} for e in ents]
    cited = [{"id": x, "rank": i + 1} for i, x in enumerate(sources)]
    out.data["recorded"], run = sessions.record(ctx, sid=sid, user=a.user, key=a.session, question=a.question,
                                                resolved=resolved, intent=out.data["intent"], summary=out.summary,
                                                answer=out.data["answer"], about=about, sources=cited)
    out.queries.append(run)
    return out


def _history(ctx: ToolContext, ans: _Answer, a: AskArgs, question: str, base: dict[str, Any]) -> ToolOutput:
    """ask, "what did I ask about X": the asker's earlier questions from the graph (user_questions, every session of
    theirs), newest first: those ABOUT the entities the question names, else those containing the words after
    "about", else all. A recall is not itself recorded."""
    if not a.user:
        return ToolOutput(summary="No conversation history without a user", queries=ans.queries, data={
            **base, "intent": "history", "questions": [], "answer": "No conversation history: pass user (e.g. "
            "person:hana-costa) with each question and it is remembered in your session."})
    q = padded(question)
    ents = link(ans.read(ctx, "link_entities", q=q), q)
    m = re.search(r"\babout\b(.*)$", question.lower())
    text = re.sub(r"[^a-z0-9:@._ -]", "", m.group(1)).strip() if m and not ents else ""
    rows = ans.read(ctx, "user_questions", user=a.user, session=None, ids=[e["id"] for e in ents],
                    text=text or None, limit=10)
    subject = ", ".join(_label(e) for e in ents) or (f"'{text}'" if text else "anything")
    answer = (f"You asked {_n(len(rows), 'question')} about {subject}, newest first: "
              + "; ".join(_recap(r) for r in rows) + "." if rows
              else f"No earlier question of yours about {subject} is on record.")
    linked = [{k: e[k] for k in ("id", "kind", "name", "matched")} | {"carried": False} for e in ents]
    return ToolOutput(summary=f"{len(rows)} earlier question{'s' if len(rows) != 1 else ''} of {a.user} about "
                              f"{subject}",
                      data={**base, "intent": "history", "linked": linked, "questions": rows, "answer": answer},
                      queries=ans.queries, highlight=Highlight(nodes=[e["id"] for e in ents]))


def _label(e: dict[str, Any]) -> str:
    return e["id"] if e["kind"] in ("change", "ticket", "incident") else e["name"]


def _recap(r: dict[str, Any]) -> str:
    read = f" (read as '{r['resolved']}')" if r.get("resolved") else ""
    cited = [x["title"] or x["id"] for x in r["sources"]][:3]
    with_ = f"; answered with {', '.join(repr(x) for x in cited)}" if cited else "; no sources"
    return f"'{r['text']}'{read} ({r['intent']}, {_ts(r['at'])}{with_})"


class QuestionsArgs(BaseModel):
    user: str = Field(pattern=sessions.USER, description="Whose questions: the user given to ask, e.g. "
                      "person:hana-costa")
    about: str | None = Field(None, max_length=120, description="Only questions about this service, team, person, "
                              "change or ticket (by name or id: payments-gw, chg:pgw-pool-1), else containing this "
                              "text; default: every question")
    session: str | None = Field(None, pattern=sessions.KEY, description="Only this session (the key given to ask); "
                                "default: every session of the user")
    limit: int = Field(10, ge=1, le=50, description="How many questions, newest first")

    @field_validator("user", "session", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> Any:
        return sessions.lower(v)


@tool(agent=False)
def my_questions(ctx: ToolContext, a: QuestionsArgs) -> ToolOutput:
    """Conversation memory: what a user asked the company brain before, newest first, each with what it was about,
    how a pronoun in it was read, the answer given and the sources it cited. Filter to one subject ("what did I ask
    about payments-gw") or one session. ask records a question when given a user; a tenant reset clears them."""
    ans = _Answer()
    ents: list[dict[str, Any]] = []
    text = None
    if a.about:
        q = padded(a.about)
        ents = link(ans.read(ctx, "link_entities", q=q), q)
        text = None if ents else a.about.lower().strip()
    rows = ans.read(ctx, "user_questions", user=a.user, session=a.session, ids=[e["id"] for e in ents], text=text,
                    limit=a.limit)
    what = (" about " + ", ".join(_label(e) for e in ents)) if ents else (f" containing '{text}'" if text else "")
    where = f" in session {a.session}" if a.session else ""
    return ToolOutput(summary=f"{len(rows)} question{'s' if len(rows) != 1 else ''} by {a.user}{what}{where}",
                      data={"questions": rows, "linked": [{k: e[k] for k in ("id", "kind", "name", "matched")}
                                                           for e in ents]},
                      queries=ans.queries, highlight=Highlight(nodes=[e["id"] for e in ents]))

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
