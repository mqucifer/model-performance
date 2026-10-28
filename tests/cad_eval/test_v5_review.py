"""What V5's live run showed (mqucifer/model-performance#40, the operator's read of
press-fit-pin 20261027T141934Z): calls the harness cost the model, and a wrong answer
from `measure`. Each fixed, each held here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cad_eval import plan
from cad_eval.cases import CASES
from cad_eval.session import Session
from cad_eval.tools import EDIT, WRITE_BASE, PartTools
from tests.cad_eval.fakes import FakeWorkspace
from tests.cad_eval.test_records import Scripted
from tests.cad_eval.test_run import call


def tools(tmp_path: Path) -> PartTools:
    t = PartTools(
        tmp_path, FakeWorkspace(directory=tmp_path, writes={"part.step": "s"}), arm="base"
    )
    t.plan_passed = True
    return t


# 1. `run` on `write` and `edit`: a boolean, and the script to run its own argument.


def test_run_is_a_boolean_and_the_script_has_its_own_argument() -> None:
    for spec in (WRITE_BASE, EDIT):
        properties = spec["function"]["parameters"]["properties"]
        assert properties["run"]["type"] == "boolean"
        assert properties["run_script"]["type"] == "string"


def test_run_sent_as_the_text_true_or_false_is_read_as_the_boolean(tmp_path: Path) -> None:
    """V5's call 4: `"run": "true"` got "There's no file true." and cost a call."""
    t = tools(tmp_path)
    found = t.call("write", json.dumps({"path": "make.py", "content": "x = 1\n", "run": "true"}))
    assert found.outcome == "ok" and "Ran make.py: exit 0" in found.reply
    found = t.call("write", json.dumps({"path": "b.py", "content": "x = 1\n", "run": "False"}))
    assert found.outcome == "ok" and "Ran" not in found.reply


def test_run_script_runs_another_script_after(tmp_path: Path) -> None:
    t = tools(tmp_path)
    (tmp_path / "make.py").write_text("import params\n")
    args = {"path": "params.py", "content": "SIZE = 1\n", "run_script": "make.py"}
    found = t.call("write", json.dumps(args))
    assert found.outcome == "ok" and t.workspace.commands[-1] == ["python", "make.py"]
    missing = t.call("write", json.dumps({**args, "run_script": "nope.py"}))
    assert missing.why == "no_file" and "nope.py" in missing.reply


# 3. The plan check's messages say what's accepted.


def test_a_missing_list_says_send_an_empty_one() -> None:
    p = {"parts": [{"name": "pin", "file": "part.step"}], "sizes": [], "fits": []}
    said = plan.check(CASES["press-fit-pin"].spec(), ["part.step"], p).said()
    assert said == ["`interfaces` is missing: send [] if there are none"]


def test_a_value_that_isnt_one_number_says_what_is_accepted() -> None:
    """V5's call 2: a placement "Z=0 to Z=16" was told only "has no number"."""
    p = {
        "parts": [{"name": "pin", "file": "part.step"}],
        "interfaces": [],
        "sizes": [{"name": "placement", "value": "Z=0 to Z=16", "source": "spec", "quote": "x"}],
        "fits": [],
    }
    said = plan.check(CASES["press-fit-pin"].spec(), ["part.step"], p).said()[0]
    assert "one number with its unit" in said and '16 or "16 mm"' in said
    assert "a size for each" in said


# 4. Each call's reasoning, by its size, in the records.


def test_each_call_records_its_reasonings_size(tmp_path: Path) -> None:
    message = {"role": "assistant", "content": "", "reasoning_content": "think " * 10}
    message["tool_calls"] = [call("blocked", {"reason": "x"}, 1)]
    answer: dict[str, Any] = {
        "choices": [{"message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    session = Session("spec", tools(tmp_path), Scripted([answer]), "m", tmp_path / "e.jsonl")
    session.run()
    event = next(json.loads(x) for x in (tmp_path / "e.jsonl").open() if '"call"' in x)
    assert event["reasoning_chars"] == 60
    assert session.reasoning_chars == 60


# The blind oracle at 12e1540: wall-hook's width was the whole part's.


def test_a_section_span_measures_the_feature_not_the_part() -> None:
    from cad_eval import checks  # noqa: PLC0415
    from cad_eval.cases import Member, SectionSpan  # noqa: PLC0415

    seat = Member("part", section_spans=(SectionSpan("strap_seat", "x", 20, "y", (35, 80)),))
    base: dict[str, Any] = {"solids": 1, "bbox": [[0, 50], [-30, 30], [-10, 10]], "volume": 1}
    narrow = {**base, "sections": [{"area": 40.0, "bbox": [[20, 20], [-5, 5], [-4, 0]]}]}
    wide = {**base, "sections": [{"area": 400.0, "bbox": [[20, 20], [-22, 22], [-10, 0]]}]}
    none = {**base, "sections": [{"area": 0.0}]}
    assert [(c.name, c.ok, c.found) for c in checks.member(seat, narrow)][-1] == (
        "section.strap_seat",
        False,
        10,
    )
    assert checks.member(seat, wide)[-1].ok
    assert not checks.member(seat, none)[-1].ok
    from cad_eval import run as cad  # noqa: PLC0415

    assert cad.requests(CASES["wall-hook"])["part"]["sections"] == [{"axis": "x", "at": 20}]
