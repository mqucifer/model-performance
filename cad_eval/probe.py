"""Does the served template keep past reasoning? A probe, run only on the operator's go.

    uv run python -m cad_eval.probe --go

mqucifer/model-performance#40, A5. The base arm sends each turn's reasoning back, as
crew's session does, on the belief that Qwen's chat template renders it. If Qwen 3.8's
template follows Qwen 3's, it renders reasoning only after the last real user message,
and the session inserts user messages (a view's picture, the no-tool nudge), so each
could silently drop all the reasoning before it.

So, through LiteLLM with the builders' key, three pairs of requests, each with
`max_tokens: 1` (a token's answer, nothing more), the same but for one turn's
reasoning: after the turn, a user message; a tool reply; a tool reply then an inserted
user message. If the prompt grows by about the reasoning's tokens, it's kept. Six
calls in all. Nothing is kept but the counts, printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

REASONING = "Working it out: the web is 0.4 mm and the flaps 3 mm. " * 40
# A difference this share of the reasoning's own size (in tokens, at ~4 chars a token)
# or more means the template rendered it.
KEPT_SHARE = 0.5
CALL = {"id": "c1", "type": "function", "function": {"name": "run", "arguments": "{}"}}
TOOL = {
    "type": "function",
    "function": {
        "name": "run",
        "description": "Run it.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def conversations(reasoning: str) -> dict[str, list[dict[str, Any]]]:
    turn: dict[str, Any] = {"role": "assistant", "content": "ok"}
    tool_turn: dict[str, Any] = {"role": "assistant", "content": "", "tool_calls": [CALL]}
    if reasoning:
        turn["reasoning_content"] = reasoning
        tool_turn["reasoning_content"] = reasoning
    start = [{"role": "system", "content": "Answer briefly."}, {"role": "user", "content": "Go."}]
    reply = {"role": "tool", "tool_call_id": "c1", "content": "exit 0"}
    inserted = {"role": "user", "content": "The view you asked for: (a picture)"}
    return {
        "then_user": [*start, turn, {"role": "user", "content": "Again."}],
        "then_tool": [*start, tool_turn, reply],
        "then_tool_then_user": [*start, tool_turn, reply, inserted],
    }


def probe(send: Callable[[dict[str, Any]], dict[str, Any]], alias: str) -> dict[str, Any]:
    with_it, without = conversations(REASONING), conversations("")
    expected = len(REASONING) / 4
    found: dict[str, Any] = {"reasoning_tokens_about": round(expected)}
    for name in with_it:
        counts = []
        for messages in (with_it[name], without[name]):
            body = {"model": alias, "messages": messages, "tools": [TOOL], "max_tokens": 1}
            counts.append(int(send(body).get("usage", {}).get("prompt_tokens") or 0))
        grew = counts[0] - counts[1]
        found[name] = {
            "with": counts[0],
            "without": counts[1],
            "kept": grew >= KEPT_SHARE * expected,
        }
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad_eval.probe", description=__doc__.split("\n\n")[0])
    parser.add_argument("--go", action="store_true", help="the operator has given the go")
    parser.add_argument("--model", help="a LiteLLM alias in place of the Developer's")
    args = parser.parse_args(argv)
    if not args.go:
        print("refused: six model calls; run with --go on the operator's go", file=sys.stderr)
        return 2
    from crew_org.calls import role_spec  # noqa: PLC0415

    from common.config import load  # noqa: PLC0415
    from common.litellm import Sender, builders_key  # noqa: PLC0415

    settings = load()
    alias = args.model or str(role_spec("developer").get("llm"))
    send = Sender(settings, builders_key(settings), cap=6)
    try:
        print(json.dumps(probe(send, alias), indent=1))
    finally:
        send.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
