"""Conversation memory, per engineer and per session, in the graph: every question `ask` answers for a named user
becomes a Question node in that user's Session (ASKED; FOLLOWS the question before it), linked to what it was ABOUT
and what it was ANSWERED_WITH. That is what lets a follow-up say "it" (read against the previous question's
entities) and makes "what did I ask about payments-gw" a graph query (queries/sessions.cypher: user_questions).
It is memory about the asker, never a company fact: a user who is no Person in the graph still gets a session, and a
reset of the tenant wipes it with the rest of the memory."""

import re
import time
from typing import Any

from oncall_brain.agents.registry import ToolContext
from oncall_brain.domain.models import QueryRun

USER = r"^[a-z0-9:@._-]{1,60}$"  # a Person id (person:hana-costa), a handle (@hana.costa) or any stable name
KEY = r"^[a-z0-9_.-]{1,40}$"
THINGS = ("service", "change", "ticket", "incident", "initiative", "team")
PEOPLE, EITHER = ("person",), ("person", "team")
# Which of the previous question's entities a pronoun can stand for: the first class with a match wins; "it" and
# "they" fall back to everything the previous question was about, "he" and "she" never stand for a service.
PRONOUNS = {"it": THINGS, "its": THINGS, "they": EITHER, "them": EITHER, "their": EITHER, "theirs": EITHER,
            "he": PEOPLE, "she": PEOPLE, "him": PEOPLE, "her": PEOPLE, "his": PEOPLE, "hers": PEOPLE}
PRONOUN = re.compile(r"\b(" + "|".join(PRONOUNS) + r")\b", re.IGNORECASE)


def lower(value: Any) -> Any:
    """Users and session keys are compared as written in the graph: lowercase, no padding."""
    return value.strip().lower() if isinstance(value, str) else value


def canon(user: str) -> str:
    """One asker, however named: person:hana-costa, @hana-costa and hana-costa are the same session owner."""
    return user.removeprefix("person:").lstrip("@")


RESERVED = ("users named slack:<id> belong to /oncall in Slack, which proves them with Slack's signature; "
            "ask as yourself")


def reserved(user: Any) -> bool:
    """A self-asserted slack:<id> (HTTP API, MCP): it would read or steer that Slack user's conversation. Checked on
    the name as the session sees it, so @slack:u7 and person:slack:u7 count too."""
    return isinstance(user, str) and canon(lower(user)).startswith("slack:")


def session_id(user: str, key: str) -> str:
    return f"session:{canon(user)}:{key}"


def mention(e: dict[str, Any]) -> str:
    """How an entity is written back into a question so `link_entities` finds it again: a service, team or person
    by name; a change or ticket by the part of its id after the colon (pgw-pool-1, CR-881); an incident by its id
    (inc:0911: the part after the colon alone would read as a number)."""
    if e["kind"] == "incident":
        return e["id"]
    return e["id"].split(":", 1)[-1] if e["kind"] in ("change", "ticket") else e["name"]


def resolve(question: str, entities: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], str | None]:
    """The question with its first pronoun replaced by the previous question's entities it can stand for, those
    entities, and the pronoun. Unchanged, with no entities, when there is no pronoun or nothing it can stand for."""
    m = PRONOUN.search(question)
    if not m or not entities:
        return question, [], None
    pronoun = m.group(1).lower()
    kinds = PRONOUNS[pronoun]
    picked = [e for e in entities if e["kind"] in kinds] or (entities if kinds is not PEOPLE else [])
    if pronoun in ("it", "its") and len(picked) > 1:  # one thing: what the question was about, not its incident
        picked = [next((e for e in picked if e["kind"] != "incident"), picked[0])]
    if not picked:
        return question, [], None
    return question[:m.start()] + " and ".join(mention(e) for e in picked) + question[m.end():], picked, pronoun


def record(ctx: ToolContext, *, sid: str, user: str, key: str, question: str, resolved: str | None, intent: str,
           summary: str, answer: str, about: list[dict[str, Any]], sources: list[dict[str, Any]]
           ) -> tuple[dict[str, Any], QueryRun]:
    """Append the question to the session (record_question) under the session's own lock, not the tenant lock: no
    agent run touches sessions, and a question must never wait for an investigation. Returns what was written and
    the query run, for the trace."""
    with ctx.repo.lock(sid):
        run = ctx.repo.write("record_question", session_id=sid, user=user, key=key, at=int(time.time()),
                             text=question, resolved=resolved, intent=intent, summary=summary, answer=answer,
                             about=about, sources=sources)
    row = run.rows[0]
    return {"session": sid, "question": row["question"], "seq": row["seq"]}, run
