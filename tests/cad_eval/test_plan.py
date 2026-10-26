"""The plan stage (mqucifer/model-performance#30): a plan checked by value on the right
part against what the spec states, and the gate it holds on `write` and `run`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cad_eval import plan, skills
from cad_eval.cases import CASES
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace

WORDS = ("zero", "one", "two", "three", "four", "five", "six")
HARD = [name for name, case in CASES.items() if case.tier >= 6]


def passing(name: str) -> dict:
    """A plan giving each stated value on its part, with names of no meaning."""
    case = CASES[name]
    sizes = [
        {"part": st.part, "name": f"n{k}", "value": st.value, "source": "spec"}
        for k, st in enumerate(plan.STATED[name])
    ]
    return {
        "parts": [{"name": m.name, "file": f"{m.name}.step"} for m in case.members],
        "interfaces": [],
        "sizes": sizes,
        "fits": [],
    }


def test_every_hard_case_has_its_stated_values_on_its_own_parts() -> None:
    assert sorted(plan.STATED) == sorted(HARD)
    for name in HARD:
        members = {m.name for m in CASES[name].members}
        for st in plan.STATED[name]:
            assert st.part is None or st.part in members, (name, st)


@pytest.mark.parametrize("name", HARD)
def test_only_numbers_the_spec_states_are_checked(name: str) -> None:
    """The guard: each value (or, for a range, an end of it) is in the spec's text."""
    text = CASES[name].spec()
    numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
    numbers |= {str(k) for k, word in enumerate(WORDS) if re.search(rf"\b{word}\b", text)}
    for st in plan.STATED[name]:
        ends = {st.value, st.value - st.tol, st.value + st.tol}
        assert any(any(float(n) == e for n in numbers) for e in ends), (name, st)


@pytest.mark.parametrize("name", HARD)
def test_a_plan_with_every_stated_value_passes_whatever_its_names(name: str) -> None:
    case = CASES[name]
    checked = plan.check(name, case.outputs(), json.dumps(passing(name)))
    assert checked.passed, checked.said()


def test_a_miss_is_named_in_the_specs_words_and_logged_with_what_it_was_checked_against() -> None:
    p = passing("living-hinge")
    web = next(s for s in p["sizes"] if s["value"] == 0.4)
    web["value"] = 0.6
    checked = plan.check("living-hinge", ["part.step"], p)
    assert [m.what for m in checked.misses] == ["the web's thickness"]
    assert "0.6" in checked.said()[0] and "web's thickness" in checked.said()[0]
    assert web in checked.misses[0].checked


def test_a_value_on_the_wrong_part_doesnt_count() -> None:
    p = passing("gear-pair")
    for size in p["sizes"]:
        if size["part"] == "gear-b":
            size["part"] = "gear-a"
    checked = plan.check("gear-pair", CASES["gear-pair"].outputs(), p)
    assert [m.what for m in checked.misses] == ["gear B's teeth"]
    assert "no size on gear-b" in checked.said()[0]


def test_equal_stated_values_on_a_part_may_share_one_size() -> None:
    p = passing("pin-clevis")
    p["sizes"] = [s for s in p["sizes"] if not (s["part"] == "tongue" and s["value"] == 6.3)]
    assert plan.check("pin-clevis", CASES["pin-clevis"].outputs(), p).passed is False
    p["sizes"].append({"part": "tongue.step", "name": "hole", "value": "6.3 mm", "source": "spec"})
    assert plan.check("pin-clevis", CASES["pin-clevis"].outputs(), p).passed


def test_a_plan_of_the_wrong_shape_or_files_goes_back_saying_so() -> None:
    assert "isn't JSON" in plan.check("spur-gear", ["part.step"], "{parts").said()[0]
    p = passing("spur-gear")
    p["sizes"][0]["source"] = "guess"
    assert "source" in plan.check("spur-gear", ["part.step"], p).said()[0]
    p = passing("bolt-nut")
    p["parts"] = p["parts"][:1]
    assert "bolt.step, nut.step" in plan.check("bolt-nut", ["bolt.step", "nut.step"], p).said()[0]


def tools(tmp_path: Path, case: str = "spur-gear") -> PartTools:
    outputs = CASES[case].outputs()
    return PartTools(tmp_path, FakeWorkspace(directory=tmp_path), outputs, "refs-plan", case=case)


def test_write_and_run_wait_for_a_plan_that_agrees(tmp_path: Path) -> None:
    t = tools(tmp_path)
    write = '{"path": "make.py", "content": "x = 1"}'
    assert t.call("write", write).why == "no_plan"
    assert t.call("run", '{"path": "make.py"}').why == "no_plan"
    found = t.call("plan", json.dumps({"plan": json.dumps(passing("spur-gear"))}))
    assert found.outcome == "ok" and found.detail["misses"] == []
    assert t.call("write", write).outcome == "ok"
    assert (t.plans, t.plan_passed, t.plan_misses) == (1, True, 0)


def test_the_gate_opens_after_three_plans_that_miss(tmp_path: Path) -> None:
    t = tools(tmp_path)
    p = passing("spur-gear")
    p["sizes"] = [s for s in p["sizes"] if s["value"] != 6]  # the bore
    for k in range(plan.ATTEMPTS):
        found = t.call("plan", json.dumps({"plan": json.dumps(p)}))
        assert found.outcome == "failed" and found.why == "misses"
        assert found.detail["misses"][0]["what"] == "the bore"
        assert ("open now" in found.reply) is (k == plan.ATTEMPTS - 1)
    assert t.call("write", '{"path": "make.py", "content": "x = 1"}').outcome == "ok"
    assert (t.plans, t.plan_passed, t.plan_misses) == (3, False, 3)


def test_other_arms_have_no_gate_and_the_plan_arm_says_how() -> None:
    assert skills.ARMS["refs-plan"] == (("references",), False, ("plan",))
    assert skills.image_for("refs-plan") == skills.image_for("refs")
    assert skills.PLAN_LINE in skills.start_for("refs-plan")
