"""One part's session: the model writes CadQuery with the tools until it calls `done` or `blocked`.

A conversation a call at a time through `common.litellm.Sender`, so every call goes
to LiteLLM on :4000 with the builders' key, inside the run's cap. Each tool call is
judged as it's carried out (`cad_eval/tools.py`), and each judgement is told back to
the model, so a malformed call costs it a turn, as in the crew's session.

Every ending is handled, with the crew session's words where they mean the same:

- `done`: it named a script that exists. The checks then run on what it makes.
- `blocked`: it called `blocked` (stop `said`), or it was stopped: 3 replies in a row
  with no tool call (`no_tool_call`), or an hour of model time (`backstop`).
- `interrupted`: the call cap (`call_cap`), a failed call (`call_failed`), or a
  container that stopped answering (`workspace_gone`): nothing about the part.

Its events, prompts and answers included, go only to the run's records on the Mac.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cad_eval.tools import OUTPUT, Gone, PartTools
from common.litellm import CallCapReached

QUIET_LIMIT = 3
BACKSTOP_S = 60 * 60
QUIET = "Call a tool to go on, or `done` or `blocked`."
SYSTEM = f"""You make 3D-printable parts in CadQuery 2.8 (Python), from a spec, \
with tools, in a directory of your own.

- Write a script with `write`. It must save the part as STEP to `{OUTPUT}` in the \
directory, with `cq.exporters.export(result, "{OUTPUT}")`. Units are millimetres.
- Run it with `run`, and measure what it made with `inspect` against the spec.
- When it matches the spec, call `done` with the script's path. It's run again from \
a clean start and checked. If the spec can't be made, call `blocked` and say why.
- The part must be one closed solid, placed exactly as the spec says. There's no \
network, and only CadQuery and its dependencies are installed."""
# The harder cases' (`cad_eval/cases.py`): one script writes every file the spec names.
SYSTEM_CASE = """You make 3D-printable parts in CadQuery 2.8 (Python), from a spec, \
with tools, in a directory of your own.

- Write a script with `write`. It must save each part the spec names as STEP, to the \
file the spec names for it, with `cq.exporters.export(part, "<name>.step")`. Units \
are millimetres.
- Run it with `run`, and measure what it made with `inspect` against the spec.
- When it matches the spec, call `done` with the script's path. It's run again from \
a clean start and checked. If the spec can't be made, call `blocked` and say why.
- Each part must be closed solids, as many as the spec says, placed exactly as the \
spec says. There's no network, and only CadQuery and its dependencies are installed."""


@dataclass
class Ending:
    how: str  # done, blocked or interrupted
    stop: str = ""
    said: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    spec: str
    tools: PartTools
    send: Callable[[dict[str, Any]], dict[str, Any]]
    alias: str
    events: Path
    max_tokens: int = 65536
    system: str = SYSTEM
    backstop_s: float = BACKSTOP_S
    calls: int = 0
    model_s: float = 0.0
    usage: Counter[str] = field(default_factory=Counter)
    # Each tool call's outcome (ok, malformed, ill_typed, failed), and calls by tool.
    outcomes: Counter[str] = field(default_factory=Counter)
    by_tool: Counter[str] = field(default_factory=Counter)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def run(self) -> Ending:
        self.messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.spec},
        ]
        quiet = 0
        while True:
            if self.model_s >= self.backstop_s:
                return self._ended(Ending("blocked", "backstop"))
            answer, ending = self._call()
            if ending is not None:
                return self._ended(ending)
            message = answer["choices"][0].get("message") or {}
            tool_calls = message.get("tool_calls") or []
            kept: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
            if tool_calls:
                kept["tool_calls"] = tool_calls
            self.messages.append(kept)
            if not tool_calls:
                quiet += 1
                if quiet >= QUIET_LIMIT:
                    return self._ended(Ending("blocked", "no_tool_call"))
                self.messages.append({"role": "user", "content": QUIET})
                continue
            quiet = 0
            try:
                ending = self._tools(tool_calls)
            except Gone as gone:
                return self._ended(Ending("interrupted", "workspace_gone", {"error": str(gone)}))
            if ending is not None:
                return self._ended(ending)

    def _call(self) -> tuple[dict[str, Any], Ending | None]:
        body = {
            "model": self.alias,
            "messages": self.messages,
            "tools": self.tools.specs,
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
        }
        began = time.monotonic()
        try:
            answer = self.send(body)
        except CallCapReached as capped:
            return {}, Ending("interrupted", "call_cap", {"error": str(capped)})
        except Exception as exc:  # noqa: BLE001 - any failed call ends it as interrupted
            return {}, Ending("interrupted", "call_failed", {"error": f"{type(exc).__name__}"})
        finally:
            self.model_s += time.monotonic() - began
        self.calls += 1
        self.usage.update(usage(answer))
        choices = answer.get("choices") if isinstance(answer, dict) else None
        if not choices:
            return {}, Ending("interrupted", "call_failed", {"error": "no choices"})
        self._record(
            "call",
            n=self.calls,
            finish=choices[0].get("finish_reason"),
            message=choices[0].get("message"),
            usage=usage(answer),
        )
        return answer, None

    def _tools(self, tool_calls: list[Any]) -> Ending | None:
        for call in tool_calls:
            function = (call.get("function") if isinstance(call, dict) else None) or {}
            name = function.get("name")
            judged = self.tools.call(name, function.get("arguments"))
            self.outcomes[judged.outcome] += 1
            if isinstance(name, str):
                self.by_tool[name] += 1
            self._record(
                "tool",
                name=name,
                outcome=judged.outcome,
                why=judged.why,
                arguments=function.get("arguments"),
                reply=judged.reply,
            )
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") if isinstance(call, dict) else None,
                    "content": judged.reply or "ok",
                }
            )
            if judged.outcome == "ok" and name in ("done", "blocked"):
                # The rest of the turn's calls aren't carried out, nor counted.
                return Ending(name, "" if name == "done" else "said", judged.args or {})
        return None

    def _record(self, kind: str, **detail: Any) -> None:
        with self.events.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, **detail}, default=str) + "\n")

    def _ended(self, ending: Ending) -> Ending:
        self._record("ended", how=ending.how, stop=ending.stop, said=ending.said)
        return ending


def usage(answer: Any) -> dict[str, int]:
    """Token counts off a response as LiteLLM reports them; a shape nobody expected is none."""
    raw = answer.get("usage") if isinstance(answer, dict) else None
    if not isinstance(raw, dict):
        return {}
    found = {
        k: raw[k] for k in ("prompt_tokens", "completion_tokens") if isinstance(raw.get(k), int)
    }
    for key, detail in (
        ("reasoning_tokens", "completion_tokens_details"),
        ("cached_tokens", "prompt_tokens_details"),
    ):
        value = (raw.get(detail) or {}).get(key)
        if isinstance(value, int):
            found[key] = value
    return found
