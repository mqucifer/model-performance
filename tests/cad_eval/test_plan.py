"""`plan` before code, checked against the model's own quotes (mqucifer/model-performance#40, A1).

There's no per-case key of values: a size the model says comes from the spec must quote
the spec's words, and its value must be in that quote. A miss names the model's own
entry and quote, never a value the evaluation holds. The same check works on any spec,
seen or not."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cad_eval import plan
from cad_eval.cases import CASES
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace

SPEC = CASES["living-hinge"].spec()


def good() -> dict[str, Any]:
    return {
        "parts": [{"name": "hinge", "file": "part.step", "what": "two flaps and a web"}],
        "interfaces": [],
        "sizes": [
            {
                "part": "hinge",
                "name": "web_t",
                "value": 0.4,
                "source": "spec",
                "quote": "It is 0.4 mm thick, flush with the flaps' bottom faces",
            },
            {
                "part": "hinge",
                "name": "flap length",
                "value": "30 mm",
                "source": "spec",
                "quote": "each 30 mm along X, 20 mm along Y and 3 mm thick",
            },
            {"part": "hinge", "name": "fillet", "value": 0.2, "source": "chosen"},
            {"part": "hinge", "name": "total", "value": 64, "source": "derived", "from": "2*30+4"},
        ],
        "fits": [],
    }


def test_a_plan_whose_spec_values_are_in_its_quotes_passes() -> None:
    checked = plan.check(SPEC, ["part.step"], json.dumps(good()))
    assert checked.passed, checked.said()


def test_names_and_layout_of_the_quote_dont_matter() -> None:
    p = good()
    # The spec's bold markup, line breaks and case aren't the model's to copy.
    p["sizes"][0]["quote"] = "it is 0.4 mm   thick,\nflush with the flaps' bottom faces"
    assert plan.check(SPEC, ["part.step"], p).passed


def test_a_quote_not_in_the_spec_is_a_miss_in_the_models_own_words() -> None:
    p = good()
    p["sizes"][0]["quote"] = "the web is 0.4 mm thick"
    checked = plan.check(SPEC, ["part.step"], p)
    assert [m.entry["name"] for m in checked.misses] == ["web_t"]
    said = checked.said()[0]
    assert "web_t" in said and "the web is 0.4 mm thick" in said and "isn't in the spec" in said


def test_a_value_not_in_its_quote_is_a_miss() -> None:
    p = good()
    p["sizes"][0]["value"] = 0.6
    checked = plan.check(SPEC, ["part.step"], p)
    assert "doesn't give 0.6" in checked.said()[0]


def test_a_miss_never_tells_a_value_the_model_didnt_write() -> None:
    p = good()
    p["sizes"][0]["value"] = 0.6
    p["sizes"][0]["quote"] = "a web"
    for said in plan.check(SPEC, ["part.step"], p).said():
        assert "0.4" not in said


def test_chosen_and_derived_sizes_are_recorded_not_judged() -> None:
    p = good()
    p["sizes"][2]["value"] = 999
    p["sizes"][3]["value"] = -1
    assert plan.check(SPEC, ["part.step"], p).passed


def test_a_spec_size_needs_a_quote_and_a_plan_needs_its_shape_and_files() -> None:
    p = good()
    del p["sizes"][0]["quote"]
    assert "quote" in plan.check(SPEC, ["part.step"], p).said()[0]
    assert "isn't JSON" in plan.check(SPEC, ["part.step"], "{parts").said()[0]
    p = good()
    p["sizes"][0]["source"] = "guess"
    assert "source" in plan.check(SPEC, ["part.step"], p).said()[0]
    assert "box.step, lid.step" in plan.check(SPEC, ["box.step", "lid.step"], good()).said()[0]


def test_a_reference_size_quotes_a_reference_the_session_can_read() -> None:
    p = good()
    p["sizes"].append(
        {
            "part": "hinge",
            "name": "m4 hole",
            "value": 4.5,
            "source": "reference",
            "quote": "M4 | 4.3 | 4.5",
        }
    )
    assert plan.check(SPEC, ["part.step"], p).passed
    p["sizes"][-1]["quote"] = "M4 clearance is 4.5 mm"
    assert "isn't in the references" in plan.check(SPEC, ["part.step"], p).said()[0]


def test_the_check_needs_no_case_and_works_on_any_spec() -> None:
    spec = "# A plate\n\n**Size:** a plate 70 by 50 mm and 3 mm thick."
    p = {
        "parts": [{"name": "plate", "file": "part.step"}],
        "interfaces": [],
        "sizes": [{"name": "t", "value": 3, "source": "spec", "quote": "3 mm thick"}],
        "fits": [],
    }
    assert plan.check(spec, ["part.step"], p).passed


def tools(tmp_path: Path) -> PartTools:
    return PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm="base", spec=SPEC)


def test_write_edit_and_run_wait_for_a_plan_that_agrees(tmp_path: Path) -> None:
    t = tools(tmp_path)
    write = '{"path": "make.py", "content": "x = 1\\n"}'
    assert t.call("write", write).why == "no_plan"
    assert t.call("run", '{"path": "make.py"}').why == "no_plan"
    found = t.call("plan", json.dumps({"plan": json.dumps(good())}))
    assert found.outcome == "ok" and found.detail["misses"] == []
    assert t.call("write", write).outcome == "ok"
    assert t.call("edit", '{"path": "make.py", "old": "x = 1", "new": "x = 2"}').outcome == "ok"
    assert (t.plans, t.plan_passed, t.plan_misses) == (1, True, 0)


def test_the_gate_opens_after_three_plans_that_miss_and_each_miss_is_logged(tmp_path: Path) -> None:
    t = tools(tmp_path)
    p = good()
    p["sizes"][0]["value"] = 0.6
    for k in range(plan.ATTEMPTS):
        found = t.call("plan", json.dumps({"plan": json.dumps(p)}))
        assert found.outcome == "failed" and found.why == "misses"
        # Logged with the entry it was checked against, so a false miss shows.
        assert found.detail["misses"][0]["entry"]["name"] == "web_t"
        assert ("open now" in found.reply) is (k == plan.ATTEMPTS - 1)
    assert t.call("write", '{"path": "make.py", "content": "x = 1\\n"}').outcome == "ok"
    assert (t.plans, t.plan_passed, t.plan_misses) == (3, False, 3)


def test_there_is_no_per_case_answer_key() -> None:
    assert not hasattr(plan, "STATED")


def test_a_base_arm_run_records_its_plan_on_the_row(tmp_path: Path) -> None:
    from cad_eval import container
    from tests.cad_eval.test_cases import go
    from tests.cad_eval.test_run import Run, answer, call

    replies = [
        answer(call("plan", {"plan": json.dumps(good())}, 1)),
        answer(call("write", {"path": "make.py", "content": "x = 1\n", "run": True}, 2)),
        answer(call("done", {"script": "make.py"}, 3)),
    ]
    r = Run(tmp_path, replies)
    row = go(r, "living-hinge", arm="base")
    assert row["image"] == container.IMAGE_V2
    assert (row["plans"], row["plan_passed"], row["plan_misses"]) == (1, True, 0)
    assert (row["views"], row["image_tokens"]) == (0, 0)
    assert row["calls_to_first_compile"] == 2
