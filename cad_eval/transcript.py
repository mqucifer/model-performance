"""Each call's exact request, rebuilt from a run's events (mqucifer/model-performance#40, V4).

A request is the whole conversation so far, so keeping each one whole would repeat
its prefix on every call. The session keeps, before each call, a `request` event
with only what's new: the messages added since the last call, and the tools and
parameters when they change. When it changes an earlier message (a picture replaced
by a note, older reasoning cleared), it keeps a `rewrite` event. Replaying them in
order gives each request as it was sent, and a test holds the session to that.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def rebuild(events: Path, n: int) -> dict[str, Any]:
    """The body of call `n` (from 1), as it went to LiteLLM."""
    messages: list[dict[str, Any]] = []
    tools: Any = None
    params: dict[str, Any] = {}
    with events.open(encoding="utf-8") as fh:
        for line in fh:
            event = json.loads(line)
            if event.get("kind") == "rewrite":
                messages[event["index"]] = event["message"]
            elif event.get("kind") == "request":
                messages = messages[: event["from"]] + event["append"]
                tools = event.get("tools", tools)
                params = event.get("params", params)
                if event["n"] == n:
                    return {**params, "messages": copy.deepcopy(messages), "tools": tools}
    raise LookupError(f"no request {n} in {events}")
