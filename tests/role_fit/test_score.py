"""An answer is scored in its request's own form, as crew's call layer would have refused it."""

from __future__ import annotations

import json

from crew_org.calls import RUNAWAY_CHARS, response_format
from crew_org.crews.criteria_crew import CriteriaCheck

from role_fit import score

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "Thing",
        "schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}, "n": {"type": "integer"}},
            "required": ["summary", "n"],
        },
    },
}
JSON_REQUEST = {"model": "crew-analysis", "messages": [], "response_format": SCHEMA}
TWO_PART = {"model": "crew-code-think", "messages": [], "extra_body": {"ebnf": "root ::= ..."}}


def test_a_json_answer_holds_to_its_requests_schema() -> None:
    ok = score.score(JSON_REQUEST, "Thing", json.dumps({"summary": "done", "n": 1}), "stop")
    assert ok == {"valid": True, "why": None, "empty": False, "runaway": False, "cut": False}
    assert score.score(JSON_REQUEST, "Thing", '{"summary": "done"}', "stop")["why"] == "schema"
    assert score.score(JSON_REQUEST, "Thing", "{not json", "stop")["why"] == "not_json"


def test_empty_cut_and_runaway_are_named_before_the_form() -> None:
    assert score.score(JSON_REQUEST, "Thing", "  \n", "stop")["why"] == "empty"
    assert score.score(JSON_REQUEST, "Thing", '{"summary": "do', "length")["why"] == "length"
    ran = score.score(JSON_REQUEST, "Thing", "{" + " " * RUNAWAY_CHARS, "runaway")
    assert ran["runaway"] and ran["why"] == "runaway"
    assert score.ran_away("{" + " " * RUNAWAY_CHARS) and not score.ran_away("{}")


def test_a_value_cut_at_a_quote_is_refused_as_crew_refuses_it() -> None:
    cut = json.dumps({"summary": "accepts exactly two values:", "n": 1})
    assert score.score(JSON_REQUEST, "Thing", cut, "stop")["why"] == "cut_at_quote"


def test_a_two_part_answer_names_each_block_once() -> None:
    head = {"summary": "edit", "edits": [{"path": "a.py", "source": "b1"}]}
    good = json.dumps(head) + "\n\n@@@ b1 @@@\nx = 1\n@x\n\n@@@ end @@@\n"
    assert score.score(TWO_PART, "FirstOrDone", good, "stop")["valid"]
    unnamed = (
        json.dumps({"summary": "edit", "source": "@@one@@"}) + "\n@@@ b1 @@@\nx\n@@@ end @@@\n"
    )
    assert score.score(TWO_PART, "FirstOrDone", unnamed, "stop")["why"] == "block_names"
    unanswered = json.dumps({"summary": "edit", "source": "b2"}) + "\n"
    assert score.score(TWO_PART, "FirstOrDone", unanswered, "stop")["why"] == "block_names"
    unclosed = json.dumps(head) + "\n@@@ b1 @@@\nx = 1\n"
    assert score.score(TWO_PART, "FirstOrDone", unclosed, "stop")["why"] == "blocks"


def test_a_case_is_dated_unless_the_pinned_crew_asks_the_same_form() -> None:
    current = {"messages": [], "response_format": response_format(CriteriaCheck)}
    assert not score.dated(current, "CriteriaCheck")
    assert score.dated(JSON_REQUEST, "CriteriaCheck")  # same model name, another schema
    assert score.dated(JSON_REQUEST, "NoSuchModel")
    assert score.dated(TWO_PART, "FirstOrDone")
    assert not score.dated({"messages": []}, "Free")


def test_a_current_case_is_also_held_to_crews_model() -> None:
    current = {"messages": [], "response_format": response_format(CriteriaCheck)}
    assert score.score(current, "CriteriaCheck", "{}", "stop")["why"] in ("schema", "model")


def test_hedges_are_counted_per_10k_characters_of_thinking() -> None:
    assert score.hedges_per_10k("") is None
    thinking = "Wait, no. Actually it's fine. Let me re-check that.".ljust(1000, "x")
    assert score.hedges_per_10k(thinking) == 30.0
    assert score.hedges_per_10k("waiter actuality") == 0.0
