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

import copy
import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from cad_eval.tools import OUTPUT, Gone, PartTools
from common.litellm import CallCapReached

QUIET_LIMIT = 3
BACKSTOP_S = 60 * 60
# A prompt this size or larger is compacted first: crew's own line (the Sponsor's 125k,
# `crew_org/session/conversation.py`), in a 262,144-token window that keeps 65,536 for
# the answer. One still this size after compacting ends the run, as the budget's.
COMPACT_AT = 125_000
# Characters a token, for what's come since the last measured prompt: 2.7, measured on
# the served model by `cad_eval.probe` (2026-10-27: ~2,160 characters, ~800 tokens).
CHARS_PER_TOKEN = 2.7
COMPACTED = "(compacted: {what})"
# A picture's tokens in the next prompt, before a response reports them: V5's view
# was 576 (press-fit-pin, 20261027T141934Z).
PICTURE_TOKENS = 600
QUIET = "Call a tool to go on, or `done` or `blocked`."
SHOWN_BEFORE = "(An earlier view was here: only the latest view is kept.)"
SYSTEM = f"""You make 3D-printable parts in CadQuery 2.8 (Python), from a spec, \
with tools, in a directory of your own.

- Write a script with `write`. It must save the part as STEP to `{OUTPUT}` in the \
directory, with `cq.exporters.export(result, "{OUTPUT}")`. Units are millimetres.
- Run it with `run`, and measure what it made with `inspect` against the spec.
- When it matches the spec, call `done` with the script's path. It's run again from \
a clean start and checked. If the spec can't be made, call `blocked` and say why.
- The part must be one closed solid, placed exactly as the spec says. There's no \
network, and only CadQuery and its dependencies are installed."""
# The harder cases' (`cad_eval/cases.py`): one script writes every file the case names.
# Each file is named here, in the prompt: a one-part case's spec names none, and on
# 2026-10-25 the first run's shelf bracket, told only "the file the spec names", wrote
# `bracket.step` (mqucifer/model-performance#16).
SYSTEM_CASE = """You make 3D-printable parts in CadQuery 2.8 (Python), from a spec, \
with tools, in a directory of your own.

- Write a script with `write`. It must save {saves}, with \
`cq.exporters.export(part, "<file>")`. Units are millimetres.
- Run it with `run`, and measure what it made with `inspect` against the spec.
- When it matches the spec, call `done` with the script's path. It's run again from \
a clean start and checked. If the spec can't be made, call `blocked` and say why.
- Each part must be closed solids, as many as the spec says, placed exactly as the \
spec says. There's no network, and only CadQuery and its dependencies are installed."""


# The base arm's (mqucifer/model-performance#40): each tool named once for what it's
# for, so there's one way to check a fit, not three; what's installed, exactly; and the
# orientation: the version, the two layers of the API, and to check a name first.
SYSTEM_BASE = """You make 3D-printable parts in CadQuery 2.8.0 (Python), from a spec, \
with tools, in a directory of your own.

- Save {saves}, with `cq.exporters.export(part, "<file>")`. Units are millimetres.
- First send your plan with `plan`. Then write a script with `write`, change it with \
`edit`, read a file back with `read`, and run it with `run` (or `run: true` on `write` \
or `edit`).
- Check what it made against the spec: `inspect` (whether it's a valid closed solid, \
its bounding box and volume), `measure` (holes, distances, the gap between your files, \
where faces are) and `view` (a picture).
- When it matches the spec, call `done` with the script's path. It's run again from \
a clean start and checked. If the spec can't be made, call `blocked` and say why.
- Each part must be closed solids, as many as the spec says, placed exactly as the \
spec says.

Installed: CadQuery 2.8.0 and OCP 7.9.3 (its binding of the OCCT kernel), with numpy, \
scipy and trimesh. There's no network. CadQuery has two layers, each with its own \
methods: the Workplane chain (`cq.Workplane`, whose methods return a new Workplane) and \
the shapes it holds (`cq.Solid`, `cq.Face`, `cq.Wire` and the rest; `.val()` takes one \
from a Workplane). Check a name before you use it: `lookup` finds names in the \
installed library, and `docs` searches CadQuery's own 2.8.0 documentation."""


def system_for(outputs: list[str], base: bool = False) -> str:
    """A harder case's prompt, naming the STEP file each of its parts is saved to."""
    if len(outputs) == 1:
        saves = f"the part as STEP to `{outputs[0]}` in the directory"
    else:
        named = ", ".join(f"`{o}`" for o in outputs)
        saves = f"each part the spec names as STEP, to its own file in the directory: {named}"
    return (SYSTEM_BASE if base else SYSTEM_CASE).format(saves=saves)


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
    # A line after the spec: the skill arm's start line, naming the skills it may read.
    start: str = ""
    backstop_s: float = BACKSTOP_S
    calls: int = 0
    # The call after which a `run` first exited 0 with every output written.
    first_compile: int | None = None
    # The views drawn, each kept in the records (`view`, mqucifer/model-performance#29).
    views: int = 0
    # Calls that ran to the token limit (`length`) or that crew's cut ended (`runaway`):
    # each one's reasoning and content tokens, as far as it reached.
    runaways: list[dict[str, int]] = field(default_factory=list)
    model_s: float = 0.0
    usage: Counter[str] = field(default_factory=Counter)
    # Each tool call's outcome (ok, malformed, ill_typed, failed), and calls by tool.
    outcomes: Counter[str] = field(default_factory=Counter)
    by_tool: Counter[str] = field(default_factory=Counter)
    messages: list[dict[str, Any]] = field(default_factory=list)
    # The model each call's response named, in order (`identity.py`: read, not typed).
    served: list[str] = field(default_factory=list)
    # The base arm's (#40, A5): each turn's reasoning goes back as it came, as crew's
    # session sends it, and a prompt at `compact_at` is compacted first.
    keep_reasoning: bool = False
    compact_at: int = COMPACT_AT
    compactions: int = 0
    # The last call's measured prompt, and how long its messages were as characters.
    last_prompt: int = 0
    last_chars: int = 0
    # The reasoning's size over the run, in characters: each call's is in its event.
    reasoning_chars: int = 0
    # Each tool reply's tool, by its message's index, and what compaction needs of it:
    # the file it was about, whether it ran something, and whether it was done.
    answered_by: dict[int, str] = field(default_factory=dict)
    replies: dict[int, dict[str, Any]] = field(default_factory=dict)
    # How many messages the records already hold, and the last tools and parameters
    # they hold: each `request` event keeps only what's new (`transcript.py`).
    logged: int = 0
    logged_tools: str = ""
    logged_params: dict[str, Any] = field(default_factory=dict)

    def run(self) -> Ending:
        self.messages = [
            {"role": "system", "content": self.system},
            {
                "role": "user",
                "content": f"{self.spec}\n\n{self.start}" if self.start else self.spec,
            },
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
            if self.keep_reasoning and message.get("reasoning_content"):
                # Qwen's template renders each past turn's reasoning: it goes back as it came.
                kept["reasoning_content"] = message["reasoning_content"]
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
            if self.first_compile is None and self.tools.compiled:
                self.first_compile = self.calls
            if ending is not None:
                return self._ended(ending)

    def rewrite(self, index: int, content: Any) -> None:
        """Change an earlier message's content, and keep the change in the records."""
        self.messages[index] = {**self.messages[index], "content": content}
        self._record("rewrite", index=index, message=self.messages[index])

    def _request(self, body: dict[str, Any]) -> None:
        """What's new in this call's request, as `transcript.rebuild` replays it."""
        wire = getattr(self.send, "wire", None)
        sent = wire(body) if callable(wire) else body
        params = {k: v for k, v in sent.items() if k not in ("messages", "tools")}
        tools = json.dumps(sent["tools"], sort_keys=True)
        event: dict[str, Any] = {
            "n": self.calls + 1,
            "from": self.logged,
            "append": copy.deepcopy(self.messages[self.logged :]),
        }
        if tools != self.logged_tools:
            event["tools"] = sent["tools"]
            event["tools_sha"] = hashlib.sha256(tools.encode()).hexdigest()
            self.logged_tools = tools
        if params != self.logged_params:
            event["params"] = params
            self.logged_params = params
        self._record("request", **event)
        self.logged = len(self.messages)

    def _chars(self) -> int:
        """The messages' size as text, a picture counted as its tokens, not its base64
        (a view's PNG is 30 to 60k characters: the review of #41)."""
        pictures = 0
        shown = []
        for m in self.messages:
            if isinstance(m.get("content"), list):
                pictures += sum(1 for p in m["content"] if p.get("type") == "image_url")
                m = {**m, "content": [p for p in m["content"] if p.get("type") != "image_url"]}
            shown.append(m)
        return len(json.dumps(shown)) + int(pictures * PICTURE_TOKENS * CHARS_PER_TOKEN)

    def estimate(self) -> int:
        """The next prompt's tokens: the last one's, measured, plus what's come since."""
        if not self.last_prompt:
            return int((self._chars() + len(json.dumps(self.tools.specs))) / CHARS_PER_TOKEN)
        return self.last_prompt + int((self._chars() - self.last_chars) / CHARS_PER_TOKEN)

    def compact(self) -> None:
        """crew's compaction, on this conversation, each change a recorded rewrite.

        - Every assistant turn before the newest loses its reasoning.
        - **Each file's latest full text stays whole** (the review of #41: an edit after
          a write left no copy of the script): its last `write` (the call), or its last
          `read` (the reply), and every `edit` of it after that, call and reply.
        - The latest reply that ran something stays whole, from `run` or from `write`
          or `edit` with `run`, and so do the newest turn's replies.
        - Every other `write` or `edit` call keeps its own keys, its text shrunk to a
          note, and every other tool reply shrinks to one line.
        """
        last = max((i for i, m in enumerate(self.messages) if m["role"] == "assistant"), default=-1)
        full: dict[str, set[tuple[str, int, int]]] = {}
        for i, m in enumerate(self.messages):
            for k, called in enumerate(m.get("tool_calls") or []):
                function = called.get("function") or {}
                path = str(_arguments(function.get("arguments")).get("path"))
                if function.get("name") == "write":
                    full[path] = {("call", i, k)}
                elif function.get("name") == "edit":
                    full.setdefault(path, set()).add(("call", i, k))
            info = self.replies.get(i)
            if info and info["ok"] and info["name"] == "read" and info["whole"]:
                full[str(info["path"])] = {("reply", i, -1)}
            elif info and info["ok"] and info["name"] == "edit":
                full.setdefault(str(info["path"]), set()).add(("reply", i, -1))
        kept = set().union(*full.values()) if full else set()
        ran = [i for i, info in self.replies.items() if info["ran"]]
        latest_ran = max(ran, default=-1)
        for i, m in enumerate(self.messages):
            if m["role"] == "assistant" and i != last:
                changed = dict(m)
                if m.get("reasoning_content"):
                    changed["reasoning_content"] = ""
                calls = []
                for k, called in enumerate(m.get("tool_calls") or []):
                    function = called.get("function") or {}
                    name = function.get("name")
                    if name in ("write", "edit") and ("call", i, k) not in kept:
                        args = _arguments(function.get("arguments"))
                        size = len(str(function.get("arguments")))
                        note = COMPACTED.format(what=f"{size} characters")
                        texts = ("content",) if name == "write" else ("old", "new")
                        short = {**args, **{t: note for t in texts if t in args}}
                        called = {
                            **called,
                            "function": {**function, "arguments": json.dumps(short)},
                        }
                    calls.append(called)
                if calls:
                    changed["tool_calls"] = calls
                if changed != m:
                    self.messages[i] = changed
                    self._record("rewrite", index=i, message=changed)
            elif (
                m["role"] == "tool"
                and i < last
                and i != latest_ran
                and ("reply", i, -1) not in kept
            ):
                content = str(m.get("content") or "")
                if not content.startswith("(compacted:"):
                    first = content.splitlines()[0][:120] if content else ""
                    what = f"{self.answered_by.get(i, 'tool')}: {first}"
                    self.rewrite(i, COMPACTED.format(what=what))
        self.compactions += 1

    def _call(self) -> tuple[dict[str, Any], Ending | None]:
        if self.keep_reasoning and self.last_prompt and self.estimate() >= self.compact_at:
            before = self.estimate()
            self.compact()
            self._record("compacted", estimated=before, estimated_after=self.estimate())
            if self.estimate() >= self.compact_at:
                said = {"estimated": self.estimate(), "limit": self.compact_at}
                return {}, Ending("interrupted", "context_full", said)
        sent_chars = self._chars()
        body = {
            "model": self.alias,
            "messages": self.messages,
            "tools": self.tools.specs,
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
        }
        self._request(body)
        at = datetime.now(UTC)
        began = time.monotonic()
        try:
            answer = self.send(body)
        except CallCapReached as capped:
            return {}, Ending("interrupted", "call_cap", {"error": str(capped)})
        except Exception as exc:  # noqa: BLE001 - any failed call ends it as interrupted
            said: dict[str, Any] = {"error": f"{type(exc).__name__}"}
            stop = "call_failed"
            if isinstance(exc, httpx.HTTPStatusError):
                # The status only: the body can echo the request.
                said["status"] = exc.response.status_code
                if said["status"] == 400 and self.keep_reasoning:
                    # A prompt the window won't hold is the budget's, not the server's.
                    estimated = self.estimate()
                    if estimated >= self.compact_at:
                        stop = "context_full"
                        said.update(estimated=estimated, limit=self.compact_at)
            return {}, Ending("interrupted", stop, said)
        finally:
            took = time.monotonic() - began
            self.model_s += took
        self.calls += 1
        message = (answer.get("choices") or [{}])[0].get("message") or {}
        thought = len(str(message.get("reasoning_content") or ""))
        self.reasoning_chars += thought
        self.last_prompt = int(usage(answer).get("prompt_tokens") or 0)
        self.last_chars = sent_chars
        # What served it: LiteLLM's deployment id from its headers. The response's
        # `model` is the alias the proxy was asked for, so it can't show a change.
        headers = dict(getattr(self.send, "served", None) or {})
        served = headers.get("x-litellm-model-id") or None
        if served:
            self.served.append(served)
        self.usage.update(usage(answer))
        choices = answer.get("choices") if isinstance(answer, dict) else None
        if not choices:
            return {}, Ending("interrupted", "call_failed", {"error": "no choices"})
        if choices[0].get("finish_reason") in ("length", "runaway"):
            used = usage(answer)
            reasoning = used.get("reasoning_tokens", 0)
            self.runaways.append(
                {"reasoning": reasoning, "content": used.get("completion_tokens", 0) - reasoning}
            )
        self._record(
            "call",
            n=self.calls,
            # The proxy's request id, which its spend log keeps (`common/spend.py`).
            response_id=answer.get("id"),
            at=at.isoformat(timespec="seconds"),
            seconds=round(took, 1),
            # The reasoning's size, beside its tokens in `usage` when the stream gives them.
            reasoning_chars=thought,
            served_model=served,
            served=headers,
            finish=choices[0].get("finish_reason"),
            message=choices[0].get("message"),
            usage=usage(answer),
        )
        return answer, None

    def _tools(self, tool_calls: list[Any]) -> Ending | None:
        picture: str | None = None
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
                **({"detail": judged.detail} if judged.detail is not None else {}),
            )
            reply: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": call.get("id") if isinstance(call, dict) else None,
                "content": judged.reply or "ok",
            }
            # Which tool answered, kept here, not sent: compaction keeps the latest run's.
            self.answered_by[len(self.messages)] = str(name)
            args = _arguments(function.get("arguments"))
            self.replies[len(self.messages)] = {
                "name": name,
                "path": args.get("path"),
                "ok": judged.outcome == "ok",
                "ran": judged.outcome == "ok"
                and (name == "run" or "\n\nRan " in str(judged.reply or "")),
                # A read of the whole file, not part of it (the second review of #41).
                "whole": bool((judged.detail or {}).get("whole")) if name == "read" else False,
            }
            self.messages.append(reply)
            if judged.image:
                picture = judged.image
                self._keep_view(judged.image)
            if judged.outcome == "ok" and name in ("done", "blocked"):
                # The rest of the turn's calls aren't carried out, nor counted.
                return Ending(name, "" if name == "done" else "said", judged.args or {})
        if picture:
            self._show(picture)
        return None

    def _keep_view(self, image: str) -> None:
        """The view's picture, kept in the run's records beside its events."""
        import base64  # noqa: PLC0415

        views = self.events.parent / "views"
        views.mkdir(exist_ok=True)
        self.views += 1
        (views / f"{self.views}.png").write_bytes(base64.b64decode(image))

    def _show(self, image: str) -> None:
        """The turn's latest view, to the model as a picture of its own: a tool's reply
        can't carry an image. An earlier picture is replaced by a note (a rewrite the
        records keep), so only the latest is in the conversation."""
        for index, message in enumerate(self.messages):
            if message.get("role") == "user" and isinstance(message.get("content"), list):
                self.rewrite(index, SHOWN_BEFORE)
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "The view you asked for:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
                ],
            }
        )

    def _record(self, kind: str, **detail: Any) -> None:
        with self.events.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, **detail}, default=str) + "\n")

    def _ended(self, ending: Ending) -> Ending:
        self._record("ended", how=ending.how, stop=ending.stop, said=ending.said)
        return ending


def _arguments(raw: Any) -> dict[str, Any]:
    try:
        found = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


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
        ("image_tokens", "prompt_tokens_details"),
    ):
        value = (raw.get(detail) or {}).get(key)
        if isinstance(value, int):
            found[key] = value
    return found
