"""The base arm's context (mqucifer/model-performance#40, A5, A6): the model's reasoning
kept between calls, as crew's session keeps it; compaction at crew's 125k; a prompt
that won't fit ended as the budget's, not the infrastructure's; and a cap of 50 the
model is never told."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from cad_eval import run as cad
from cad_eval import transcript
from cad_eval.session import Session
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace
from tests.cad_eval.test_records import Scripted
from tests.cad_eval.test_run import call


def thought(*tool_calls: dict[str, Any], reasoning: str = "", prompt: int = 1000) -> dict:
    message = {"role": "assistant", "content": "", "reasoning_content": reasoning}
    message["tool_calls"] = list(tool_calls)
    return {
        "choices": [{"message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": 10},
    }


def session(tmp_path: Path, replies: list[dict], arm: str = "base", **kw: Any) -> tuple:
    tools = PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm=arm)
    tools.plan_passed = True
    send = Scripted(replies)
    found = Session("spec", tools, send, "m", tmp_path / "events.jsonl", **kw)
    found.keep_reasoning = arm == "base"
    return found, send


def write(n: int, content: str = "x = 1\n") -> dict:
    return call("write", {"path": "make.py", "content": content}, n)


def test_the_base_arm_keeps_each_turns_reasoning(tmp_path: Path) -> None:
    s, send = session(
        tmp_path,
        [
            thought(write(1), reasoning="the web is 0.4"),
            thought(call("blocked", {"reason": "x"}, 2)),
        ],
    )
    s.run()
    assistant = [m for m in send.bodies[1]["messages"] if m["role"] == "assistant"]
    assert assistant[0]["reasoning_content"] == "the web is 0.4"


def test_v1s_arms_drop_it_as_they_ran(tmp_path: Path) -> None:
    s, send = session(
        tmp_path / "v1",
        [thought(write(1), reasoning="r"), thought(call("blocked", {"reason": "x"}, 2))],
        arm="skill",
    )
    (tmp_path / "v1").mkdir(exist_ok=True)
    s.run()
    assistant = [m for m in send.bodies[1]["messages"] if m["role"] == "assistant"]
    assert "reasoning_content" not in assistant[0]


def test_a_prompt_at_the_line_is_compacted_and_every_request_still_rebuilds(
    tmp_path: Path,
) -> None:
    big = "y = 2\n" * 400
    replies = [
        thought(write(1, big), reasoning="first " * 200, prompt=1000),
        thought(call("run", {"path": "make.py"}, 2), reasoning="second " * 200, prompt=2000),
        thought(write(3, big), reasoning="third", prompt=3000),
        thought(call("blocked", {"reason": "x"}, 4), prompt=1500),
    ]
    s, send = session(tmp_path, replies, compact_at=3000)
    s.run()
    last = send.bodies[-1]["messages"]
    assistant = [m for m in last if m["role"] == "assistant"]
    # Earlier turns' reasoning cleared; the newest turn's kept.
    assert [a.get("reasoning_content") for a in assistant] == ["", "", "third"]
    replies_seen = [m["content"] for m in last if m["role"] == "tool"]
    # The latest run's reply and the newest turn's reply stay whole; the rest shrink.
    assert replies_seen[0].startswith("(compacted: write")
    assert replies_seen[1].startswith("exit 0")
    assert s.compactions == 1
    for n, sent in enumerate(send.bodies, start=1):
        assert transcript.rebuild(tmp_path / "events.jsonl", n) == sent


def test_a_prompt_still_too_long_after_compacting_ends_as_the_budgets(tmp_path: Path) -> None:
    replies = [
        thought(write(1, "z = 3\n" * 2000), prompt=1000),
        thought(call("blocked", {"reason": "x"}, 2)),
    ]
    s, _ = session(tmp_path, replies, compact_at=1500)
    ending = s.run()
    assert (ending.how, ending.stop) == ("interrupted", "context_full")
    row = {"ending": "interrupted", "stop": "context_full", "compiles": None}
    assert cad.fault(row, {}, {}) == "budget"


def test_a_400_for_a_prompt_over_the_line_is_context_full(tmp_path: Path) -> None:
    def refuse(_: dict) -> dict:
        request = httpx.Request("POST", "http://x/chat/completions")
        raise httpx.HTTPStatusError(
            "400", request=request, response=httpx.Response(400, request=request)
        )

    tools = PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm="base")
    s = Session("spec " * 100, tools, refuse, "m", tmp_path / "events.jsonl", compact_at=50)
    s.keep_reasoning = True
    ending = s.run()
    assert ending.stop == "context_full" and ending.said["status"] == 400


def test_the_base_arms_cap_is_50_and_the_model_isnt_told_it() -> None:
    assert cad.CAP_BASE == 50
    tools = PartTools(Path("."), FakeWorkspace(), arm="base")
    from cad_eval.session import system_for  # noqa: PLC0415

    said = system_for(["part.step"], base=True) + json.dumps(tools.specs)
    assert "50" not in said and " cap" not in said.lower()


def template(drops_before_last_user: bool):
    """A stand-in server: prompt tokens as a template that renders reasoning would count
    them, dropping it before the last user message if it's Qwen 3's."""

    def send(body: dict) -> dict:
        messages = body["messages"]
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        tokens = 0
        for i, m in enumerate(messages):
            tokens += len(str(m.get("content") or "")) // 4 + 5
            if m.get("reasoning_content") and not (drops_before_last_user and i < last_user):
                tokens += len(m["reasoning_content"]) // 4
        return {"usage": {"prompt_tokens": tokens}}

    return send


def test_the_probe_tells_a_template_that_keeps_reasoning_from_one_that_drops_it() -> None:
    from cad_eval import probe  # noqa: PLC0415

    kept = probe.probe(template(False), "m")
    assert all(kept[k]["kept"] for k in ("then_user", "then_tool", "then_tool_then_user"))
    qwen3 = probe.probe(template(True), "m")
    assert qwen3["then_tool"]["kept"] is True
    assert qwen3["then_user"]["kept"] is False
    assert qwen3["then_tool_then_user"]["kept"] is False


def test_the_probe_wont_run_without_the_operators_go() -> None:
    from cad_eval import probe  # noqa: PLC0415

    assert probe.main([]) == 2
