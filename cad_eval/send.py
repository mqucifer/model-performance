"""The CAD session's sender: each call streamed, its tool calls assembled, cut as crew cuts.

A call asked for whole waits for its last token. On 2026-10-25 two of the harder
cases' calls thought towards the Developer's 65,536-token limit at about 20 tokens a
second under load, and the client's one-hour timeout ended them first, with nothing
recorded but the timeout. Streamed, a call's reads keep arriving, so it runs to its
end, and the records hold what it reached.

It is role-fit's `StreamingSender` (`role_fit/send.py`) with one thing more: that one
assembles the answer's content and thinking, and a CAD session lives on its tool
calls, which arrive in pieces, by index. The cut is crew's own (`crew_org.calls`):
the stream is closed once the content runs on as whitespace past `RUNAWAY_CHARS`.
There's no other limit (the Sponsor, 2026-10-25, "production parity"): a call that
thinks to the token limit ends as `length`, and the session counts it as a runaway.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from crew_org.calls import RUNAWAY_CHARS

from common.litellm import CallCapReached, Sender


class StreamingSender(Sender):
    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.calls >= self.cap:
            raise CallCapReached(f"the run's cap of {self.cap} calls is reached")
        if self.alias:
            body = {**body, "model": self.alias}
        self.models.add(str(body.get("model")))
        self.calls += 1
        if self.ticking():
            self.tick_calls += 1
        body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        content: list[str] = []
        thinking: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish: str | None = None
        response_id = ""
        run = 0
        with self._client.stream("POST", "/chat/completions", json=body) as response:
            if response.status_code >= 400:
                # The status only: a body can echo the request, and this text reaches the record.
                raise httpx.HTTPStatusError(
                    f"LiteLLM answered {response.status_code}",
                    request=response.request,
                    response=response,
                )
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                response_id = chunk.get("id") or response_id
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    thinking.append(delta.get("reasoning_content") or "")
                    piece = delta.get("content") or ""
                    if piece:
                        content.append(piece)
                        kept = piece.rstrip()
                        run = run + len(piece) if not kept else len(piece) - len(kept)
                    for part in delta.get("tool_calls") or []:
                        assemble(calls, part)
                    finish = choice.get("finish_reason") or finish
                if run >= RUNAWAY_CHARS:
                    finish = "runaway"
                    break
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content),
            "reasoning_content": "".join(thinking),
        }
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return {
            "id": response_id,
            "choices": [{"message": message, "finish_reason": finish}],
            "usage": usage,
        }


def assemble(calls: dict[int, dict[str, Any]], part: dict[str, Any]) -> None:
    """One streamed piece of a tool call into the call at its index: the id and name
    come once, the arguments in pieces."""
    index = int(part.get("index") or 0)
    call = calls.setdefault(
        index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
    )
    call["id"] = part.get("id") or call["id"]
    function = part.get("function") or {}
    call["function"]["name"] += function.get("name") or ""
    call["function"]["arguments"] += function.get("arguments") or ""
