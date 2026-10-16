"""Pronoun resolution, the history intent and user normalisation are pure functions."""

from oncall_brain.services.brain import AskArgs, intent_of
from oncall_brain.services.sessions import resolve, session_id

SVC = {"id": "svc:payments-gw", "kind": "service", "name": "payments-gw"}
TEAM = {"id": "team:payments", "kind": "team", "name": "Payments"}
HANA = {"id": "person:hana-costa", "kind": "person", "name": "Hana Costa"}
CHG = {"id": "chg:pgw-pool-1", "kind": "change", "name": "Lower the pool"}


def test_a_pronoun_is_read_as_the_previous_entities_it_can_stand_for():
    assert resolve("and who is on call for it?", [SVC, HANA]) == ("and who is on call for payments-gw?", [SVC], "it")
    assert resolve("Does she know it?", [SVC, HANA]) == ("Does Hana Costa know it?", [HANA], "she")  # first pronoun
    assert resolve("why did they make it", [CHG, TEAM]) == ("why did Payments make it", [TEAM], "they")
    # Nobody for "them" to stand for: everything the previous question was about; a change by its short id.
    assert resolve("who owns them", [SVC, CHG]) == ("who owns payments-gw and pgw-pool-1", [SVC, CHG], "them")
    assert resolve("who is he", [SVC]) == ("who is he", [], None)  # a service is never "he"
    assert resolve("who owns kafka", [SVC]) == ("who owns kafka", [], None)
    assert resolve("who owns it", []) == ("who owns it", [], None)
    assert resolve("is itself fine? its", [SVC]) == ("is itself fine? payments-gw", [SVC], "its")  # whole words


def test_history_is_recognised_before_the_other_intents_and_users_are_normalised():
    assert intent_of("what did I ask about who owns kafka") == "history"  # "owns" and "ask" would match otherwise
    assert intent_of("What have I asked about payments-gw?") == "history"
    assert intent_of("my last questions") == "history" and intent_of("ask Hana about kafka") == "expert"
    a = AskArgs(question="q", user=" Person:Hana-Costa ", session="Claude-Code")
    assert (a.user, a.session) == ("person:hana-costa", "claude-code")
    assert session_id("person:hana-costa", "default") == "session:hana-costa:default"
    assert session_id("@hana.costa", "cli") == "session:hana.costa:cli"
