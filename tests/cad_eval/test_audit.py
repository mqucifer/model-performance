"""The case audit, both ways, all 21 harder cases (mqucifer/model-performance#40, V2).

Every hidden check traces to its spec's text: stated there, derived from it by a named
standard or arithmetic, a judgment the window must take every defensible answer to, or
the frame the spec gives. And every value the spec states has a check, or is listed as
unchecked with why. `cad_eval/audit.json` holds it; `cad_eval/audit.py` lists the checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from cad_eval import audit
from cad_eval.cases import CASES
from cad_eval.plan import normal

AUDIT = Path(audit.__file__).parent / "audit.json"
HARD = [name for name, case in CASES.items() if case.tier >= 6]
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def entries() -> dict[str, Any]:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_every_harder_case_is_audited_and_nothing_else() -> None:
    assert sorted(entries()) == sorted(HARD)


@pytest.mark.parametrize("name", HARD)
def test_every_check_traces_to_the_text(name: str) -> None:
    case = CASES[name]
    found = entries()[name]["checks"]
    listed = [c["check"] for c in audit.checks(case)]
    assert sorted(found) == sorted(listed), set(found) ^ set(listed)
    spec = normal(case.spec())
    for check, entry in found.items():
        assert entry["class"] in audit.CLASSES, check
        assert entry["says"].strip(), check
        if entry["class"] in ("stated", "frame"):
            for quote in entry["quotes"]:
                assert normal(quote) in spec, (check, quote)
        if entry["class"] == "derived":
            assert entry["quotes"] or entry["says"], check


@pytest.mark.parametrize("name", HARD)
def test_every_value_the_text_states_maps_to_a_check_that_holds_it(name: str) -> None:
    """Each number the spec states is named, in `values`, by a check that holds it, or
    is listed as unchecked with why (the review of #41: a number in any quote counted,
    whether its check held it or not)."""
    case = CASES[name]
    case_audit = entries()[name]
    held: set[float] = set()
    for check, entry in case_audit["checks"].items():
        quoted = {float(n) for q in entry.get("quotes", []) for n in NUMBER.findall(normal(q))}
        for value in entry.get("values", []):
            # A check names only what its own quotes state.
            assert float(value) in quoted, (name, check, value)
            held.add(float(value))
    unchecked = {
        float(n) for q in case_audit.get("unchecked", {}) for n in NUMBER.findall(normal(q))
    }
    stated = {float(n) for n in NUMBER.findall(normal(case.spec()))}
    missing = sorted(stated - held - unchecked)
    assert missing == [], f"{name}: the spec states {missing}, which no check holds"


def test_unchecked_values_say_why() -> None:
    for name, case_audit in entries().items():
        for quote, why in case_audit.get("unchecked", {}).items():
            assert normal(quote) in normal(CASES[name].spec()), (name, quote)
            assert why.strip(), (name, quote)


def test_no_check_can_never_fail() -> None:
    """A sample that emits no check is caught, and no case has one (the review of #41:
    this test couldn't fail, since the 0-1 shares were dropped before it looked)."""
    from cad_eval.cases import Case, Member, Sample  # noqa: PLC0415

    idle = Sample("idle", ((0.0, 0.0, 0.0),), (0.0, 1.0))
    planted = Case("planted", 6, (Member("part", samples=(idle,)),))
    assert audit.never_fails(planted) == ["part/idle"]
    for name in HARD:
        assert audit.never_fails(CASES[name]) == [], name
