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
def test_every_value_the_text_states_has_a_check_or_says_why_not(name: str) -> None:
    case = CASES[name]
    case_audit = entries()[name]
    covered = " ".join(
        normal(q) for e in case_audit["checks"].values() for q in e.get("quotes", [])
    )
    covered += " " + " ".join(normal(q) for q in case_audit.get("unchecked", {}))
    numbers_covered = {float(n) for n in NUMBER.findall(covered)}
    stated = {float(n) for n in NUMBER.findall(normal(case.spec()))}
    missing = sorted(stated - numbers_covered)
    assert missing == [], f"{name}: the spec states {missing}, which no check or note covers"


def test_unchecked_values_say_why() -> None:
    for name, case_audit in entries().items():
        for quote, why in case_audit.get("unchecked", {}).items():
            assert normal(quote) in normal(CASES[name].spec()), (name, quote)
            assert why.strip(), (name, quote)


def test_no_check_can_never_fail() -> None:
    """A share whose window is 0 to 1 passes whatever it measures: none is listed."""
    for name in HARD:
        for check in audit.checks(CASES[name]):
            if check["check"].split("/", 1)[1].startswith("share."):
                assert check["wants"] != [0.0, 1.0], (name, check)
