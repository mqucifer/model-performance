"""One part end to end, with a scripted model through `Sender` and a fake container: every
ending leaves a row of numbers and its records, and nothing behind."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from cad_eval import run as cad
from cad_eval.parts import PARTS
from common import results
from common.config import load
from common.litellm import Sender
from tests.cad_eval.fakes import FakeWorkspace, Ran
from tests.cad_eval.test_checks import measured

SCRIPT = 'import cadquery as cq\ncq.exporters.export(cq.Workplane().box(1, 1, 1), "part.step")\n'


def call(name: str, arguments: Any, n: int = 0) -> dict[str, Any]:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": f"c{n}-{name}", "type": "function", "function": {"name": name, "arguments": raw}}


def answer(*tool_calls: dict[str, Any]) -> dict[str, Any]:
    message = {"role": "assistant", "content": "", "tool_calls": list(tool_calls) or None}
    return {
        "choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 30},
            "prompt_tokens_details": {"cached_tokens": 600},
        },
    }


GOOD = [
    answer(call("write", {"path": "part.py", "content": SCRIPT})),
    answer(call("run", {"path": "part.py"})),
    answer(call("inspect", {"path": "part.step"})),
    answer(call("done", {"script": "part.py"})),
]


class Run:
    def __init__(self, tmp_path: Path, replies: list[Any], **fake: Any) -> None:
        self.settings = load(home=tmp_path)
        self.results = tmp_path / "results"
        self.workspace = FakeWorkspace(writes={"part.step": "step"}, **fake)
        self.bodies: list[dict[str, Any]] = []
        queue = iter(replies)

        def reply(request: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(request.content))
            got = next(queue)
            if isinstance(got, httpx.Response):
                return got
            # A reply's `served` is LiteLLM's response headers, as the proxy sends them.
            headers = got.get("served") or {}
            body = {k: v for k, v in got.items() if k != "served"}
            return httpx.Response(200, json=body, headers=headers)

        self.send = Sender(
            self.settings,
            "k",
            cap=cad.CAP_PER_PART,
            transport=httpx.MockTransport(reply),
            tick=lambda: False,
        )

    def go(self, name: str = "spacer", **kw: Any) -> dict[str, Any]:
        def held(directory: Path, _: str) -> FakeWorkspace:
            self.workspace.directory = directory
            return self.workspace

        kw.setdefault("image_id", lambda: "sha256:abc")
        # LiteLLM's spend log, read in a test as empty: never the proxy's database.
        kw.setdefault("read_spend", lambda _sql: "")
        # infra's record of production's serving, as a test reads it: never infra's repo.
        kw.setdefault("serving_record", lambda: {"serving_image": "lmsysorg/sglang:test"})
        # Never the Mac's own hosts file in a test.
        kw.setdefault("reached_host", lambda record: "a")
        return cad.evaluate(
            PARTS[name],
            self.settings,
            self.send,
            "crew-code-think",
            workspace_for=held,
            results_dir=self.results,
            **kw,
        )

    def records(self, row: dict[str, Any]) -> Path:
        return self.settings.records_dir / "cad_eval" / row["case"] / row["run"]


def test_a_part_made_to_spec_is_done_and_passes_every_check(tmp_path: Path) -> None:
    r = Run(tmp_path, GOOD, measured=measured("spacer"))
    row = r.go()
    assert (row["ending"], row["stop"]) == ("done", None)
    assert (row["compiles"], row["closed_mesh"], row["within_tolerance"]) == (True, True, True)
    assert row["checks_passed"] == row["checks_total"] > 0
    assert (row["calls"], row["tool_calls"], row["reliable_tool_calls"]) == (4, 4, 4)
    assert row["calls_to_done"] == 4
    assert row["tool_reliability"] == 1.0
    assert (row["writes"], row["runs"], row["inspects"]) == (1, 1, 1)
    assert (row["prompt_tokens"], row["reasoning_tokens"], row["cached_tokens"]) == (
        4000,
        120,
        2400,
    )
    assert r.workspace.stopped
    # The directory is gone, its files kept in the records with the events and checks.
    assert not any((r.settings.work_dir / "cad_eval").iterdir())
    out = r.records(row)
    assert (out / "files" / "part.py").read_text() == SCRIPT
    assert {p.name for p in out.iterdir()} == {
        "events.jsonl",
        "files",
        "checks.json",
        "result.json",
    }
    # Only numbers in the repository.
    assert results.problems(json.loads((r.results / "cad_eval.jsonl").read_text())) == []


def test_every_call_names_the_alias_and_offers_the_tools(tmp_path: Path) -> None:
    r = Run(tmp_path, GOOD, measured=measured("spacer"))
    r.go()
    assert {b["model"] for b in r.bodies} == {"crew-code-think"}
    assert [t["function"]["name"] for t in r.bodies[0]["tools"]] == [
        "write",
        "run",
        "inspect",
        "done",
        "blocked",
    ]
    assert r.bodies[0]["messages"][1]["content"] == PARTS["spacer"].spec()
    # The model is told each call's outcome before the next.
    assert r.bodies[1]["messages"][-1]["role"] == "tool"


def test_bad_calls_are_counted_by_category_and_lower_the_reliability(tmp_path: Path) -> None:
    replies = [
        answer(call("draw", {"path": "a"}, 1), call("write", "{not json", 2)),
        answer(call("write", {"path": "part.py", "content": 3})),
        answer(call("run", {"path": "missing.py"})),
        *GOOD,
    ]
    r = Run(tmp_path, replies, measured=measured("spacer"))
    row = r.go()
    assert row["ending"] == "done"
    assert (row["malformed_tool_calls"], row["ill_typed_tool_calls"]) == (2, 1)
    assert (row["failed_tool_calls"], row["reliable_tool_calls"], row["tool_calls"]) == (1, 4, 8)
    assert row["tool_reliability"] == 0.5
    outcomes = [
        json.loads(line)["outcome"]
        for line in (r.records(row) / "events.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "tool"
    ]
    assert outcomes[:4] == ["malformed", "malformed", "ill_typed", "failed"]


def test_a_part_off_spec_is_done_but_not_within_tolerance(tmp_path: Path) -> None:
    r = Run(tmp_path, GOOD, measured=measured("spacer", volume=500.0))
    row = r.go()
    assert (row["compiles"], row["within_tolerance"]) == (True, False)
    assert row["checks_passed"] == row["checks_total"] - 1


def test_a_script_that_raises_at_done_doesnt_compile(tmp_path: Path) -> None:
    # The session's own run passes; the clean run at `done` raises.
    r = Run(tmp_path, GOOD, measured=measured("spacer"), exits=[0, 1])
    row = r.go()
    assert row["ending"] == "done"
    assert (row["compiles"], row["closed_mesh"], row["within_tolerance"]) == (False, False, False)


def test_three_replies_with_no_tool_call_stop_it(tmp_path: Path) -> None:
    r = Run(tmp_path, [answer(), answer(), answer()])
    row = r.go()
    assert (row["ending"], row["stop"], row["calls"]) == ("blocked", "no_tool_call", 3)
    assert row["compiles"] is None and row["tool_reliability"] is None


def test_the_model_saying_blocked_ends_it(tmp_path: Path) -> None:
    r = Run(tmp_path, [answer(call("blocked", {"reason": "no thread size given"}))])
    row = r.go()
    assert (row["ending"], row["stop"], row["reliable_tool_calls"]) == ("blocked", "said", 1)


def test_the_cap_interrupts_it(tmp_path: Path) -> None:
    r = Run(tmp_path, [answer(call("write", {"path": "a.py", "content": ""}))] * 50)
    row = r.go()
    assert (row["ending"], row["stop"], row["calls"]) == ("interrupted", "call_cap", 40)
    assert row["calls_to_done"] is None


def test_a_failed_call_interrupts_it(tmp_path: Path) -> None:
    r = Run(tmp_path, [httpx.Response(500, json={"error": "down"})])
    row = r.go()
    assert (row["ending"], row["stop"], row["calls"]) == ("interrupted", "call_failed", 0)
    assert r.workspace.stopped


def test_a_container_that_goes_interrupts_it(tmp_path: Path) -> None:
    r = Run(tmp_path, GOOD)
    real = r.workspace.exec

    def gone(command: list[str], timeout: int = 0, stdin: str | None = None) -> Ran:
        r.workspace.lost = True
        return real(command, timeout, stdin)

    r.workspace.exec = gone  # type: ignore[method-assign]
    row = r.go()
    assert (row["ending"], row["stop"]) == ("interrupted", "workspace_gone")


def test_no_image_refuses_it_before_any_call(tmp_path: Path) -> None:
    r = Run(tmp_path, [])
    row = r.go(image_id=lambda: None)
    assert (row["ending"], row["stop"], row["calls"]) == ("refused", "no_image", 0)
    assert not r.workspace.started


def test_a_container_that_wont_start_refuses_it(tmp_path: Path) -> None:
    r = Run(tmp_path, [], start_ok=False)
    row = r.go()
    assert (row["ending"], row["stop"]) == ("refused", "container_start")
    assert r.workspace.stopped


def test_a_crash_still_leaves_a_row_and_removes_everything(tmp_path: Path) -> None:
    r = Run(tmp_path, GOOD)

    def crash(*_: Any, **__: Any) -> Ran:
        raise RuntimeError("bug")

    r.workspace.exec = crash  # type: ignore[method-assign]
    row = r.go()
    assert (row["ending"], row["stop"]) == ("crashed", "RuntimeError")
    assert r.workspace.stopped
    assert not any((r.settings.work_dir / "cad_eval").iterdir())
    assert "bug" in (r.records(row) / "result.json").read_text()


@pytest.mark.parametrize("argv", [[], ["spacer", "--first"], ["gear"]])
def test_the_cli_refuses_a_bad_choice_of_parts(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cad.main(argv)
    assert exited.value.code == 2
