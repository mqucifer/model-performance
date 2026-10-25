"""The shared sender, read as a stream and cut off when the answer runs away, as crew does.

Production asked for each answer streamed (`crew_org.calls.stream`), and closed
the stream once the answer ran on as whitespace past `RUNAWAY_CHARS`, which
ends the generation. The replay does the same, so a runaway costs what it cost
production and is counted the same way. The thinking is kept for the records
(`reasoning_content`, on the Mac), and the cap, alias and tick count are the
shared `Sender`'s.
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
                    finish = choice.get("finish_reason") or finish
                if run >= RUNAWAY_CHARS:
                    finish = "runaway"
                    break
        message = {"content": "".join(content), "reasoning_content": "".join(thinking)}
        return {
            "id": response_id,
            "choices": [{"message": message, "finish_reason": finish}],
            "usage": usage,
        }
