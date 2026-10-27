"""The CAD session's streaming sender: tool calls assembled from pieces, crew's cut, and
a call that thinks to the token limit counted as a runaway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from crew_org.calls import RUNAWAY_CHARS

from cad_eval.send import StreamingSender
from common.config import load
from tests.cad_eval.test_cases import go
from tests.cad_eval.test_run import Run


def sse(*chunks: dict[str, Any]) -> bytes:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode() + b"data: [DONE]\n\n"


def delta(finish: str | None = None, **d: Any) -> dict[str, Any]:
    return {"id": "chatcmpl-1", "choices": [{"delta": d, "finish_reason": finish}]}


def usage(completion: int, reasoning: int) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "choices": [],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": completion,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }


def sender(tmp_path: Path, streams: list[bytes], seen: list[dict[str, Any]]) -> StreamingSender:
    queue = iter(streams)

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=next(queue))

    return StreamingSender(
        load(home=tmp_path), "k", cap=5, transport=httpx.MockTransport(reply), tick=lambda: False
    )


def test_a_streamed_answers_tool_calls_are_assembled_from_their_pieces(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    stream = sse(
        delta(reasoning_content="think "),
        delta(reasoning_content="more"),
        delta(
            tool_calls=[{"index": 0, "id": "c0", "function": {"name": "write", "arguments": ""}}]
        ),
        delta(tool_calls=[{"index": 0, "function": {"arguments": '{"path": "a.py", '}}]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": '"content": "x"}'}}]),
        delta(
            tool_calls=[
                {
                    "index": 1,
                    "id": "c1",
                    "function": {"name": "run", "arguments": '{"path": "a.py"}'},
                }
            ]
        ),
        delta("tool_calls"),
        usage(50, 30),
    )
    answer = sender(tmp_path, [stream], seen)({"model": "m", "messages": []})
    assert seen[0]["stream"] is True and seen[0]["stream_options"] == {"include_usage": True}
    message = answer["choices"][0]["message"]
    assert message["reasoning_content"] == "think more"
    assert [c["function"]["name"] for c in message["tool_calls"]] == ["write", "run"]
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "path": "a.py",
        "content": "x",
    }
    assert (answer["id"], answer["choices"][0]["finish_reason"]) == ("chatcmpl-1", "tool_calls")
    assert answer["usage"]["completion_tokens"] == 50


def test_crews_cut_ends_an_answer_that_runs_on_as_whitespace(tmp_path: Path) -> None:
    stream = sse(delta(content="{"), *[delta(content=" " * 500) for _ in range(10)], delta("stop"))
    answer = sender(tmp_path, [stream], [])({"model": "m", "messages": []})
    assert answer["choices"][0]["finish_reason"] == "runaway"
    assert len(answer["choices"][0]["message"]["content"]) <= 1 + RUNAWAY_CHARS + 500


def test_a_call_that_thinks_to_the_limit_is_counted_with_its_tokens(tmp_path: Path) -> None:
    r = Run(tmp_path, [])
    streams = [
        sse(delta(reasoning_content="..."), delta("length"), usage(65536, 65500)),
        sse(delta(content="no tool"), delta("stop"), usage(10, 5)),
        sse(delta(content="no tool"), delta("stop"), usage(10, 5)),
        sse(delta(content="no tool"), delta("stop"), usage(10, 5)),
    ]
    r.send = sender(tmp_path, streams, r.bodies)
    row = go(r, "m8-bolt")
    assert row["runaways"] == 1
    assert (row["runaway_reasoning_tokens"], row["runaway_content_tokens"]) == (65500, 36)
    # It costs a call and the session goes on, as production's does.
    assert row["calls"] == 3 and row["stop"] == "no_tool_call"


def test_a_case_without_a_runaway_says_none(tmp_path: Path) -> None:
    r = Run(tmp_path, [])
    stream = sse(delta(content="hm"), delta("stop"), usage(10, 5))
    r.send = sender(tmp_path, [stream] * 3, r.bodies)
    row = go(r, "living-hinge")
    assert row["runaways"] == 0 and row["runaway_reasoning_tokens"] is None


def test_a_streamed_answer_names_the_model_that_served_it(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    served = {**delta(content="ok"), "model": "RadixArk/Qwen3.8-27B"}
    send = sender(tmp_path, [sse(served, delta("stop"))], seen)
    body = {"model": "crew-code-think", "messages": [], "tools": []}
    got = send(body)
    assert got["model"] == "RadixArk/Qwen3.8-27B"
    # What the session records as the request is what went over the wire.
    assert send.wire(body) == seen[0]
