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


def occurrences(spec: str) -> list[tuple[int, float, bool]]:
    """Each number in the spec, in order: where, what, and whether it's a tolerance."""
    return [
        (m.start(), float(m.group()), spec[max(0, m.start() - 1) : m.start()] == "±")
        for m in NUMBER.finditer(spec)
    ]


def referents(spec: str, at: int) -> list[str]:
    """What an explicit tolerance names: "±0.1 mm on the tips, the face and the bore's
    position" names three, each to be held on its own."""
    rest = spec[at:]
    rest = rest[rest.index(" on ") + 4 :] if " on " in rest[:12] else ""
    rest = re.split(r", so |, ±|; |\.(?!\d)", rest)[0]
    return [r.strip() for r in re.split(r", | and ", rest) if r.strip()]


def stated(name: str) -> list[dict[str, Any]]:
    return entries()[name]["stated"]


@pytest.mark.parametrize("name", HARD)
def test_every_number_the_text_states_has_its_own_entry(name: str) -> None:
    """One entry per occurrence, in order, each where its `at` says (the second review of
    #41: values as a set let one check of 0.1 stand for every 0.1 in the text)."""
    spec = normal(CASES[name].spec())
    found = occurrences(spec)
    listed = stated(name)
    assert len(listed) == len(found), (name, len(listed), len(found))
    for (at, value, _), entry in zip(found, listed, strict=True):
        assert float(entry["value"]) == value, (name, entry)
        text = normal(entry["at"])
        spans = [m.start() for m in re.finditer(re.escape(text), spec)]
        assert any(s <= at < s + len(text) for s in spans), (name, entry["at"], value)


@pytest.mark.parametrize("name", HARD)
def test_each_occurrence_is_held_by_named_checks_or_says_why_not(name: str) -> None:
    case_audit = entries()[name]
    spec = normal(CASES[name].spec())
    listed = {c["check"] for c in audit.checks(CASES[name])}
    for (at, value, tolerance), entry in zip(occurrences(spec), stated(name), strict=True):
        assert entry["for"], (name, entry["at"])
        if tolerance:
            named = referents(spec, at)
            if named and named != ["everything else"]:
                assert sorted(entry["for"]) == sorted(named), (name, entry["at"])
        for referent, held in entry["for"].items():
            if isinstance(held, str):
                assert held.startswith("unchecked: ") and len(held) > 15, (name, referent)
                continue
            assert held, (name, entry["at"], referent)
            for check in held:
                assert check in listed, (name, check)
                if not tolerance:
                    claims = case_audit["checks"][check].get("values", [])
                    assert value in [float(v) for v in claims], (name, check, value)


@pytest.mark.parametrize("name", HARD)
def test_no_tolerance_is_held_looser_than_the_text_gives(name: str) -> None:
    """Each check a tolerance names holds its feature at least that tightly: its own
    window's, or what the audit states for a probe (`held_to`). A size held only by its
    box's two ends is held to twice its tolerance, so it needs its size check."""
    case_audit = entries()[name]
    spec = normal(CASES[name].spec())
    tols = {c["check"]: c["tol"] for c in audit.checks(CASES[name])}
    for (_, value, tolerance), entry in zip(occurrences(spec), stated(name), strict=True):
        if not (tolerance or entry.get("tolerance")):
            continue
        for referent, held in entry["for"].items():
            if isinstance(held, str):
                continue
            for check in held:
                tol = tols[check]
                if tol is None:
                    tol = case_audit["checks"][check].get("held_to")
                assert tol is not None, (name, check, "state how tightly it holds: held_to")
                assert tol <= value + 1e-9, (name, referent, check, tol, value)
    members = {m.name for m in CASES[name].members}
    for entry in stated(name):
        for referent, held in entry["for"].items():
            if isinstance(held, str):
                continue
            for member in members:
                for axis in "xyz":
                    ends = {f"{member}/bbox.{axis}.min", f"{member}/bbox.{axis}.max"}
                    if ends <= set(held):
                        assert f"{member}/size.{axis}" in held, (name, referent, axis)


@pytest.mark.parametrize("name", HARD)
def test_a_check_names_only_values_its_own_quotes_state(name: str) -> None:
    for check, entry in entries()[name]["checks"].items():
        quoted = {float(n) for q in entry.get("quotes", []) for n in NUMBER.findall(normal(q))}
        for value in entry.get("values", []):
            assert float(value) in quoted, (name, check, value)


def test_no_check_can_never_fail() -> None:
    """A sample that emits no check is caught, and no case has one (the review of #41:
    this test couldn't fail, since the 0-1 shares were dropped before it looked)."""
    from cad_eval.cases import Case, Member, Sample  # noqa: PLC0415

    idle = Sample("idle", ((0.0, 0.0, 0.0),), (0.0, 1.0))
    planted = Case("planted", 6, (Member("part", samples=(idle,)),))
    assert audit.never_fails(planted) == ["part/idle"]
    for name in HARD:
        assert audit.never_fails(CASES[name]) == [], name
