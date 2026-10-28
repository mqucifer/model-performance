"""A tool smoke test (mqucifer/model-performance#40, V3): a scripted fake model drives a
real session, in a real v2 container, through every tool of the base arm, error paths
included, and ends with `done` on a part whose checks pass. Every request rebuilds
from the records. No model is called. Skipped where the v2 image isn't built."""

from __future__ import annotations

import contextlib
import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from cad_eval import container, transcript
from cad_eval.cases import CASES
from cad_eval.run import judge, requests
from cad_eval.session import Session, system_for
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
)
CASE = CASES["press-fit-pin"]
GOOD = (Path(__file__).parent / "reference" / "press-fit-pin.py").read_text()
BROKEN = GOOD.replace(
    'cq.exporters.export(pin, "part.step")',
    "pin.isValid()\n" + 'cq.exporters.export(pin, "part.step")',
)
# The model's own block, the one the pin presses into, as its spec describes it.
BLOCK = """import cadquery as cq
block = cq.Workplane("XY").box(20, 20, 10, centered=(True, True, False))
block = block.faces(">Z").workplane().hole(5.0)
cq.exporters.export(block, "block.step")
"""
PLAN_BAD = {
    "parts": [{"name": "pin", "file": "part.step"}],
    "interfaces": [],
    "sizes": [{"name": "d", "value": 5.1, "source": "spec", "quote": "a pin of 5.1 mm"}],
    "fits": [],
}
PLAN_GOOD = {
    **PLAN_BAD,
    "sizes": [
        {"name": "d", "value": 5.10, "source": "spec", "quote": "5.10 mm across and 16 mm long"},
        {"name": "length", "value": 16, "source": "spec", "quote": "5.10 mm across and 16 mm long"},
    ],
}

# Each step: the tool and its arguments, and what the call must come to: an outcome,
# and the rule or a phrase of its reply.
STEPS: list[tuple[str, Any, str, str]] = [
    ("plan", {"plan": json.dumps(PLAN_BAD)}, "failed", "misses"),
    ("write", {"path": "make.py", "content": GOOD}, "failed", "no_plan"),
    ("plan", {"plan": json.dumps(PLAN_GOOD)}, "ok", "The plan holds"),
    ("lookup", {"query": "Solid.fuse"}, "ok", "cq.Shape.fuse"),
    ("lookup", {"query": "fuse", "page": 0}, "failed", "not_a_page"),
    ("docs", {"query": "chamfer edges"}, "ok", "chamfer("),
    ("skill", {"name": "cadquery-selectors"}, "ok", "Selectors"),
    ("skill", {"name": "gears"}, "failed", "unknown"),
    ("write", {"path": "make.py", "content": BROKEN, "run": True}, "ok", "isn't on Workplane"),
    (
        "edit",
        {
            "path": "make.py",
            "old": "pin.isValid()",
            "new": "assert pin.val().isValid()",
            "run": True,
        },
        "ok",
        "exit 0",
    ),
    ("edit", {"path": "make.py", "old": "x", "new": "y"}, "failed", "edit.part_of_a_line"),
    ("write", {"path": "block.py", "content": BLOCK, "run": True}, "ok", "Ran block.py: exit 0"),
    ("read", {"path": "make.py"}, "ok", "lines 1-"),
    ("run", {"path": "nothing.py"}, "failed", "no_file"),
    ("inspect", {"path": "part.step"}, "ok", '"valid": true'),
    ("measure", {"path": "part.step", "query": "position >Z"}, "ok", "faces"),
    ("measure", {"path": "block.step", "query": "hole 0,0,5"}, "ok", '"diameter": 5.0'),
    ("measure", {"path": "part.step", "query": "diameter 0,0,8"}, "ok", '"kind": "outer"'),
    (
        "measure",
        {"path": "block.step", "query": "distance >Z <Z"},
        "ok",
        '"gap_along_normal": 10.0',
    ),
    ("measure", {"path": "part.step", "query": "clearance block.step"}, "ok", '"clearance"'),
    ("measure", {"path": "part.step", "query": "spin it"}, "failed", "not_a_query"),
    ("view", {"files": "part.step", "view": "section x=0"}, "ok", "picture of its own"),
    (
        "view",
        {"files": "part.step", "view": "iso", "keepouts": "block.step"},
        "ok",
        "your keep-outs (block.step)",
    ),
    ("view", {"files": "part.step", "view": "sideways"}, "failed", "not_a_query"),
    ("frobnicate", {}, "malformed", "session.arguments"),
    ("run", {"path": 3}, "ill_typed", "type"),
    ("done", {"script": "make.py"}, "ok", ""),
]


def answer(n: int, name: str, args: Any) -> dict[str, Any]:
    tool_call = {
        "id": f"c{n}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": f"step {n}",
        "tool_calls": [tool_call],
    }
    return {
        "model": "scripted",
        "choices": [{"message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 1000 + n, "completion_tokens": 5},
    }


QUIET = {
    "model": "scripted",
    "choices": [{"message": {"role": "assistant", "content": "thinking"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 900, "completion_tokens": 1},
}


def test_every_tool_and_its_error_paths_through_a_real_session(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    directory = tmp_path_factory.mktemp("smoke")
    records = tmp_path_factory.mktemp("records")
    replies = [QUIET] + [answer(n, name, args) for n, (name, args, _, _) in enumerate(STEPS, 1)]
    bodies: list[dict[str, Any]] = []
    queue = iter(replies)

    def send(body: dict[str, Any]) -> dict[str, Any]:
        bodies.append(copy.deepcopy(body))
        return next(queue)

    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(directory, f"smoke-{os.getpid()}", image=container.IMAGE_V2)
        assert held.start().ok
        try:
            tools = PartTools(directory, held, CASE.outputs(), arm="base", spec=CASE.spec())
            events = records / "events.jsonl"
            session = Session(
                CASE.spec(),
                tools,
                send,
                "scripted",
                events,
                system=system_for(CASE.outputs(), base=True),
            )
            session.keep_reasoning = True
            ending = session.run()
            final = tools.final_case(str(ending.said.get("script")), requests(CASE))
        finally:
            held.stop()

    assert ending.how == "done"
    judged = [json.loads(line) for line in events.open() if json.loads(line)["kind"] == "tool"]
    assert len(judged) == len(STEPS)
    for event, (name, _, outcome, said) in zip(judged, STEPS, strict=True):
        assert event["outcome"] == outcome, (name, event)
        assert said in (event["why"] if outcome != "ok" else event["reply"]), (name, event)
    # The quiet reply was nudged; the view's picture was sent and kept.
    assert any(
        m.get("content") == "Call a tool to go on, or `done` or `blocked`."
        for m in bodies[1]["messages"]
    )
    assert (records / "views" / "1.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # Reasoning went back, and every request rebuilds from the records.
    assert any(m.get("reasoning_content") == "step 1" for m in bodies[-1]["messages"])
    for n, sent in enumerate(bodies, start=1):
        assert transcript.rebuild(events, n) == sent
    # The part the session made passes every check of the case.
    row, found = judge(CASE, final)
    assert row["within_tolerance"], [c for c in found if not c["ok"]]


def test_a_session_can_end_blocked_saying_why(tmp_path_factory: pytest.TempPathFactory) -> None:
    directory = tmp_path_factory.mktemp("blocked")
    replies = iter([answer(1, "blocked", {"reason": "the spec gives no bore"})])
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(directory, f"smoke-b-{os.getpid()}", image=container.IMAGE_V2)
        assert held.start().ok
        try:
            tools = PartTools(directory, held, CASE.outputs(), arm="base", spec=CASE.spec())
            events = directory.parent / "blocked.jsonl"
            session = Session(CASE.spec(), tools, lambda _: next(replies), "scripted", events)
            ending = session.run()
        finally:
            held.stop()
    assert (ending.how, ending.stop, ending.said) == (
        "blocked",
        "said",
        {"reason": "the spec gives no bore"},
    )
