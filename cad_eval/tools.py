"""The session's tools, and how each call is judged: well formed, then done as asked.

The tools are the Developer's in small: `write` a file, `run` a script, `inspect` what
it made, then `done` or `blocked`. Every one acts only in the part's directory, through
its held container: `run` and `inspect` execute there, never on the host.

Each call is judged in BFCL's two categories (the Berkeley Function Calling
Leaderboard, v3):

- **AST: is it well formed?** First crew's own argument rule, `check_arguments`, over
  these tools: an object, a tool that exists, no unknown and no missing argument. A
  call it refuses is `malformed`, the benchmark's meaning exactly, so the shared count
  compares across suites. An arguments string that isn't JSON is not an object. Then
  BFCL's type check, which crew's rule doesn't make: a value of the wrong type is
  `ill_typed`.
- **Executable: did it do what it asked?** A well-formed call the tool couldn't carry
  out is `failed`: a path outside the part's directory, a file that isn't there, text
  that can't be a path (a script's content sent as its path), or content over the
  limit. A script that runs and raises is the tool doing what it was
  asked: that's the CAD code failing (`compiles`), not the call.

Everything else is `ok`. The reliability of a run is its `ok` calls over all of them.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cad_eval import hint as hint_module
from cad_eval import lookup as lookup_module
from cad_eval import measure, plan, skills
from cad_eval import render as render_module

RUN_TIMEOUT = 120
MEASURE_TIMEOUT = 180
TAIL = 4000
MAX_CONTENT = 200_000
MAX_PATH = 200
# What the script the session names at `done` must write: the part, as STEP.
OUTPUT = "part.step"
MEASURE_SOURCE = Path(measure.__file__).read_text(encoding="utf-8")
LOOKUP_SOURCE = Path(lookup_module.__file__).read_text(encoding="utf-8")
LOOKUP_TIMEOUT = 60
HINT_SOURCE = Path(hint_module.__file__).read_text(encoding="utf-8")
RENDER_SOURCE = Path(render_module.__file__).read_text(encoding="utf-8")
RENDER_TIMEOUT = 180
VIEWS = ("top", "front", "side", "iso", "exploded", "section")
# A measure the tool itself failed: not the model's query, not its part.
TOOL_FAILURES = ("the measure didn't finish", "it loads but can't be measured")
# v2's base arm (mqucifer/model-performance#40): the full toolset.
BASE = "base"
# An AttributeError's owner and name, as Python 3.12 says them.
NO_ATTRIBUTE = re.compile(
    r"AttributeError: (?:'(\w+)' object|type object '(\w+)'|module '([\w.]+)') "
    r"has no attribute '(\w+)'"
)
# What `edit` shows around a closest block, and how close it must be: crew's.
NEAR_CONTEXT = 5
NEAR_RATIO = 0.6
# The library a run's scripts ran against, read in its own container.
VERSIONS_MARK = "CAD_EVAL_VERSIONS "
VERSIONS = (
    "import json, cadquery, OCP; from importlib.metadata import version; "
    f"print({VERSIONS_MARK!r} + json.dumps({{'cadquery': cadquery.__version__, "
    "'ocp': version('cadquery-ocp')}))"
)
# The arms (mqucifer/model-performance#21): what each adds to the session's tools.
ARMS = tuple(skills.ARMS)


def _spec(
    name: str, description: str, optional: dict[str, Any] | None = None, **properties: str
) -> dict[str, Any]:
    """A tool's spec: its string arguments, all required, and any `optional` ones."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    **{k: {"type": "string", "description": v} for k, v in properties.items()},
                    **(optional or {}),
                },
                "required": list(properties),
            },
        },
    }


SPECS = [
    _spec(
        "write",
        "Write a text file in the part's directory, replacing it if it exists.",
        path="The file's path, relative to the part's directory, such as `part.py`.",
        content="The whole file.",
    ),
    _spec(
        "run",
        f"Run a Python script with CadQuery, from the part's directory, for up to "
        f"{RUN_TIMEOUT} seconds. Returns its exit code and the end of its output.",
        path="The script's path, relative to the part's directory.",
    ),
    _spec(
        "inspect",
        "Measure a STEP file: whether it's a valid shape, its solids, bounding box, "
        "volume and area, and whether its mesh is closed.",
        path="The STEP file's path, relative to the part's directory.",
    ),
    _spec(
        "done",
        f"Finish: the script is run again from a clean start, and the `{OUTPUT}` it "
        "writes is checked against the spec. The session ends.",
        script="The script that writes the part.",
    ),
    _spec(
        "blocked",
        "End without the part, saying what's missing to make it.",
        reason="What's missing.",
    ),
]
ACCEPTED = {s["function"]["name"]: s["function"]["parameters"] for s in SPECS}
# `run` on `write` and `edit` (#40, A1): one call to change a file and run a script.
RUN_AFTER = {
    "run": {
        "anyOf": [{"type": "boolean"}, {"type": "string"}],
        "description": "`true` to run this file after, or the path of the script to run "
        "after (such as `make.py`, when this file is one it imports). Optional.",
    }
}
WRITE_BASE = _spec(
    "write",
    "Write a text file in the part's directory, replacing it if it exists. With `run`, "
    "a script is run after, as `run` does.",
    RUN_AFTER,
    path="The file's path, relative to the part's directory, such as `make.py`.",
    content="The whole file.",
)
# crew's `replace_text`, behaviour and all (crew_org/session/tools.py, crew#778).
EDIT = _spec(
    "edit",
    "Replace one or more whole lines that occur exactly once in a file, quoted as the "
    "file has them, with enough lines to be unique. Applied at once, unless it would stop "
    "a Python file parsing; the reply shows the edited lines, numbered. With `run`, a "
    "script is run after, as `run` does.",
    RUN_AFTER,
    path="The file's path, relative to the part's directory.",
    old="The whole lines to replace, exactly as the file has them.",
    new="The lines to put in their place (empty to delete them).",
)


def specs_for(outputs: list[str]) -> list[dict[str, Any]]:
    """The tools for a session that writes `outputs`: the 30 parts' own, word for word,
    for `part.step` alone; for a harder case, `done` names its files."""
    if outputs == [OUTPUT]:
        return SPECS
    named = ", ".join(f"`{o}`" for o in outputs)
    done = _spec(
        "done",
        f"Finish: the script is run again from a clean start, and the files it writes "
        f"({named}) are checked against the spec. The session ends.",
        script="The script that writes the parts.",
    )
    return [done if s["function"]["name"] == "done" else s for s in SPECS]


TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict}


class Gone(RuntimeError):
    """The part's container stopped answering: the infrastructure's failure, not the model's."""


@dataclass
class Judged:
    """One tool call's outcome, and the text the model gets back."""

    name: str
    outcome: str  # ok, malformed, ill_typed or failed
    reply: str
    why: str = ""  # the rule or reason, in a word, when it isn't ok
    args: Any = None
    # A `view`'s picture, as base64 PNG: sent to the model in a message of its own.
    image: str | None = None
    painted: float | None = None  # the picture's share that isn't background
    # What the run's events keep beside the call: a plan's check, each miss with the
    # entry it was checked against.
    detail: Any = None


def parse(raw: Any) -> Any:
    """The call's arguments: an object from its JSON text, or what was sent if it isn't JSON."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except ValueError:
        return raw


def arm_specs(arm: str) -> list[dict[str, Any]]:
    """An arm's tools: crew's own `skill`, word for word, and `lookup` where the arm has
    CadQuery's skill (`cad_eval/skills.py`, `ARMS`)."""
    from crew_org.session.tools import SKILL_SPEC  # noqa: PLC0415

    found = _spec(
        "lookup",
        "Look up CadQuery's names in the installed library: the names that contain the "
        "fragment, each with its signature and docstring. `OCP.<module>` lists that "
        "module's classes.",
        query="A name or a fragment of one, such as `makeHelix` or `Workplane.sweep`.",
    )
    return [SKILL_SPEC, found] if skills.ARMS[arm][1] else [SKILL_SPEC]


MEASURE = _spec(
    "measure",
    "Measure your part, in the container: `hole x,y,z` (the hole nearest a point: its "
    "diameter and axis), `distance A B` (between two faces), `clearance FILE` (to "
    "another of your STEP files: overlap and gap), or `position A` (where faces are). "
    "A face is a selector such as `>Z`, `<X`, `%CYLINDER`, or a point `x,y,z`.",
    path="The STEP file to measure, relative to the part's directory.",
    query="What to measure, such as `hole 0,0,5` or `distance >Z <Z`.",
)
VIEW = _spec(
    "view",
    "Render your STEP files to a picture: `top`, `front`, `side`, `iso`, `exploded`, or a "
    "section such as `section x=40` (looking at the cut, the cut face in dark grey). Only "
    "the latest picture is kept in the conversation.",
    {
        "keepouts": {
            "type": "string",
            "description": "More of your own STEP files to draw translucent red, such as a "
            "board or a mating part you modelled from the spec. Optional.",
        }
    },
    files="Your STEP files to draw, separated by spaces, such as `base.step lid.step`.",
    view="The view: `iso`, `top`, `front`, `side`, `exploded` or `section x=40`.",
)
PLAN = _spec(
    "plan",
    "Your dimensioned plan, before any code. Each size says where it comes from: "
    "`spec`, quoting the spec's words that give it; `reference`, quoting the table it "
    "came from; `derived` or `chosen`. A quote is checked against the spec or the "
    "references; `write`, `edit` and `run` open once the plan holds.",
    plan='A JSON object: `parts` ([{"name", "file", "what"}]), `interfaces` ([{"between": '
    '[part, part], "what"}]), `sizes` ([{"part", "name", "value" (mm or degrees), '
    '"source", "quote"}]), and `fits` ([{"between", "kind": "clearance", "interference" '
    'or "contact", "value"}]).',
)


def base_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The base arm's tools: `write` that may run and `edit` after it, then the rest,
    then `measure`, `view` and `plan`."""
    found = []
    for spec in specs:
        if spec["function"]["name"] == "write":
            found += [WRITE_BASE, EDIT]
        else:
            found.append(spec)
    return [*found, MEASURE, VIEW, PLAN]


def _trim(text: str) -> str:
    """One leading and one trailing newline off, so quoting whole lines is forgiving."""
    text = text[1:] if text.startswith("\n") else text
    return text[:-1] if text.endswith("\n") else text


def _parse_error(source: str) -> tuple[str, int | None] | None:
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return exc.msg, exc.lineno
    return None


def _refusal(path: str, text: str, old: str, new: str) -> tuple[str, str] | None:
    """Why `old` can't be replaced in `text`, as crew's `replace_text` says it, or None."""
    from crew_org.session.tools import numbered  # noqa: PLC0415

    if not old.strip():
        return "edit.empty", "Quote the lines to replace."
    if old == new:
        return "edit.same", "`old` and `new` are the same: nothing to change."
    lines = text.splitlines()
    want = old.split("\n")
    at = [i for i in range(len(lines) - len(want) + 1) if lines[i : i + len(want)] == want]
    if len(at) > 1:
        where = ", ".join(str(i + 1) for i in at)
        return "edit.twice", (
            f"Those lines occur {len(at)} times in `{path}`, at lines {where}: quote more "
            "lines around the one you mean."
        )
    if at:
        return None
    if old in text:
        first = old.split("\n")[0]
        where = [n for n, line in enumerate(lines) if first in line]
        shown = "; ".join(f"line {n + 1}: `{lines[n].strip()}`" for n in where[:3])
        return "edit.part_of_a_line", (
            f"`old` matches only part of a line, not whole lines: {shown}. Quote whole lines."
        )
    if new and new in text:
        return (
            "edit.already",
            f"`old` isn't in `{path}`, and `new` already is: the change may be made.",
        )
    size = len(want)
    best, best_at = 0.0, -1
    for i in range(max(1, len(lines) - size + 1)):
        ratio = difflib.SequenceMatcher(
            a=old, b="\n".join(lines[i : i + size]), autojunk=False
        ).ratio()
        if ratio > best:
            best, best_at = ratio, i
    if best < NEAR_RATIO:
        return (
            "edit.not_found",
            f"Those lines aren't in `{path}`, and nothing close is: read it with a run first.",
        )
    shown = "\n".join(numbered(lines, best_at - NEAR_CONTEXT, best_at + size + NEAR_CONTEXT))
    return "edit.closest", (
        f"Those lines aren't in `{path}`. The closest block starts at line {best_at + 1}:\n{shown}"
    )


def well_formed(name: str, args: Any, accepted: dict[str, Any] = ACCEPTED) -> Judged | None:
    """The AST category: a `Judged` for a call that isn't well formed, or None."""
    from crew_org.rulebook import Refusal  # noqa: PLC0415
    from crew_org.session.tools import check_arguments  # noqa: PLC0415

    try:
        check_arguments(name, args, accepted)
    except Refusal as refused:
        return Judged(name, "malformed", str(refused), refused.rule, args)
    properties = accepted[name]["properties"]
    wrong = [
        k
        for k, v in args.items()
        if not isinstance(v, TYPES.get(properties[k].get("type", ""), object))
        or (properties[k].get("type") in ("number", "integer") and isinstance(v, bool))
    ]
    if wrong:
        said = ", ".join(f"`{k}` must be a {properties[k]['type']}" for k in wrong)
        return Judged(name, "ill_typed", f"`{name}` wasn't run: {said}.", "type", args)
    return None


def a_path(path: str) -> bool:
    """Whether `path` could name a file at all: a file's text sent as its path can't."""
    return 0 < len(path) <= MAX_PATH and path.isprintable()


def inside(directory: Path, path: str) -> Path | None:
    """`path` in the part's directory, or None for one that leads out of it."""
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or pure.parts[0] == ".crew-home":
        return None
    return directory / pure


class PartTools:
    """The tools over one part's directory and its started container."""

    def __init__(
        self,
        directory: Path,
        workspace: Any,
        outputs: list[str] | None = None,
        arm: str | None = None,
        spec: str = "",
    ) -> None:
        self.directory = directory
        # The spec's text: what `plan`'s quotes are checked against.
        self.spec = spec
        # The plan stage (the base arm's): plans checked, whether one held, its misses.
        self.planned = arm == BASE
        self.plans = 0
        self.plan_passed = False
        self.plan_misses = 0
        self.workspace = workspace
        self.outputs = outputs or [OUTPUT]
        self.arm = arm
        self.specs = specs_for(self.outputs) + (arm_specs(arm) if arm else [])
        if arm == BASE:
            self.specs = base_specs(self.specs)
        self.accepted = {s["function"]["name"]: s["function"]["parameters"] for s in self.specs}
        # Whether a `run` has exited 0 with every output written: a first compiling part.
        self.compiled = False
        self.runs: list[dict[str, Any]] = []
        # The tools' own failures, by kind, that weren't the model's: a measure that
        # didn't finish. `run.py` reads them to say whose a failure is.
        self.troubles: dict[str, int] = {}

    def call(self, name: str, raw: Any) -> Judged:
        args = parse(raw)
        bad = well_formed(name, args, self.accepted)
        if bad is not None:
            return bad
        if name in ("done", "blocked"):
            return self._ending(name, args)
        if name in ("write", "edit", "run") and self.planned and not self.plan_open:
            reply = (
                "Send your plan with `plan` first: `write`, `edit` and `run` open once it holds."
            )
            return self._failed(name, "no_plan", reply, args)
        return getattr(self, f"_{name}")(args)

    @property
    def plan_open(self) -> bool:
        """Whether the gate's open: a plan held, or `plan.ATTEMPTS` of them missed."""
        return self.plan_passed or self.plans >= plan.ATTEMPTS

    def _plan(self, args: dict[str, Any]) -> Judged:
        """The `plan` tool: its quotes against the spec and the references (`plan.py`)."""
        checked = plan.check(self.spec, self.outputs, args["plan"])
        self.plans += 1
        self.plan_misses += len(checked.said())
        detail = {
            "attempt": self.plans,
            "wrong": checked.wrong,
            "misses": [{"entry": m.entry, "why": m.why} for m in checked.misses],
        }
        if checked.passed:
            self.plan_passed = True
            reply = "The plan holds: `write`, `edit` and `run` are open."
            return Judged("plan", "ok", reply, detail=detail)
        said = "\n".join(f"- {m}" for m in checked.said())
        after = (
            "`write`, `edit` and `run` are open now."
            if self.plan_open
            else "Send the plan again with these fixed."
        )
        judged = self._failed("plan", "misses", f"The plan doesn't hold:\n{said}\n{after}", args)
        judged.detail = detail
        return judged

    def _measure(self, args: dict[str, Any]) -> Judged:
        """The `measure` tool: the model's own file and query, and nothing of the case's.

        The request carries only the path and the query: no probes, bounds, volumes or
        mates, so the model checks its part against what the spec states, never against
        the evaluation's checks (mqucifer/model-performance#28)."""
        missing = self._existing("measure", args)
        if missing is not None:
            return missing
        if len(args["query"]) > MAX_PATH or not args["query"].strip():
            reply = "`query` is one line, such as `hole 0,0,5` or `distance >Z <Z`."
            return self._failed("measure", "not_a_query", reply, args)
        found = self.measure_request({"path": args["path"], "query": args["query"]})
        error = str(found.get("error", ""))
        if error.startswith("query:"):
            return self._failed("measure", "not_a_query", error, args)
        if error.startswith(TOOL_FAILURES):
            return self._failed("measure", "unfinished", error, args)
        return Judged("measure", "ok", json.dumps(found))

    def _view(self, args: dict[str, Any]) -> Judged:
        """The `view` tool: the model's own files, and only its own, drawn by VTK."""
        files = args["files"].split()
        keepouts = str(args.get("keepouts") or "").split()
        if not files:
            return self._failed("view", "not_a_query", "Name at least one STEP file.", args)
        for name in files + keepouts:
            missing = self._existing("view", {"path": name})
            if missing is not None:
                return missing
        words = args["view"].split()
        plane = None
        if not words or words[0] not in VIEWS:
            reply = f"`view` is one of {', '.join(VIEWS[:-1])}, or `section x=40`."
            return self._failed("view", "not_a_query", reply, args)
        if words[0] == "section":
            axis, _, at = (words[1] if len(words) == 2 else "").partition("=")
            try:
                plane = {"axis": axis, "at": float(at)}
            except ValueError:
                plane = None
            if plane is None or axis not in ("x", "y", "z"):
                reply = "A section names its plane: `section x=40`, `section z=12.5`."
                return self._failed("view", "not_a_query", reply, args)
        request = {"files": files, "view": words[0], "plane": plane, "keepouts": keepouts}
        done = self.execute(
            ["python", "-I", "-", json.dumps(request)], RENDER_TIMEOUT, stdin=RENDER_SOURCE
        )
        for line in reversed(done.output.splitlines()):
            if line.startswith(render_module.MARK):
                found = json.loads(line[len(render_module.MARK) :])
                if "error" in found:
                    why = "not_a_query" if found["error"].startswith("query:") else "unfinished"
                    return self._failed("view", why, found["error"], args)
                caption = "; ".join(found.get("caption", []))
                reply = f"The {words[0]} view follows, in a picture of its own. {caption}."
                return Judged("view", "ok", reply, image=found["png"], painted=found.get("painted"))
        self.troubles["view_unfinished"] = self.troubles.get("view_unfinished", 0) + 1
        return self._failed(
            "view", "unfinished", f"The view didn't finish (exit {done.code}).", args
        )

    def _failed(self, name: str, why: str, reply: str, args: Any) -> Judged:
        return Judged(name, "failed", reply, why, args)

    def _write(self, args: dict[str, Any]) -> Judged:
        if not a_path(args["path"]):
            return self._not_a_path("write", args, "path")
        target = inside(self.directory, args["path"])
        if target is None:
            return self._failed("write", "outside", "Write only inside the part's directory.", args)
        if len(args["content"]) > MAX_CONTENT:
            return self._failed(
                "write", "too_large", f"A file is at most {MAX_CONTENT} characters.", args
            )
        script, wrong = self._run_after("write", args)
        if wrong is not None:
            return wrong
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
        except OSError as exc:
            return self._failed("write", "not_written", f"It couldn't be written: {exc}", args)
        said = f"Wrote {args['path']} ({len(args['content'])} characters)."
        return self._then_run("write", said, script)

    def _run_after(self, name: str, args: dict[str, Any]) -> tuple[str | None, Judged | None]:
        """The script a `write` or `edit` runs after (`run`): the file itself for `true`,
        a path as given, none for `false` or none; or why `run` can't be done."""
        run = args.get("run")
        if run is None or run is False:
            return None, None
        if run is True:
            return args["path"], None
        if not isinstance(run, str):
            reply = "`run` is `true`, or the path of a script to run after."
            return None, self._failed(name, "not_a_run", reply, args)
        if run != args["path"]:
            missing = self._existing(name, {**args, "run": run}, "run")
            if missing is not None:
                return None, missing
        return run, None

    def _then_run(self, name: str, said: str, script: str | None) -> Judged:
        """A change's reply, and the run after it when one was asked for."""
        if script is None:
            return Judged(name, "ok", said)
        ran = self._run({"path": script})
        return Judged(name, "ok", f"{said}\n\nRan {script}: {ran.reply}")

    def _edit(self, args: dict[str, Any]) -> Judged:
        """crew's `replace_text`, as `edit`: each refusal its own rule, and nothing run."""
        if not a_path(args["path"]):
            return self._not_a_path("edit", args, "path")
        target = inside(self.directory, args["path"])
        if target is None or not target.is_file():
            reply = f"There's no file `{args['path']}`: `write` makes a new one."
            return self._failed("edit", "edit.no_file", reply, args)
        script, wrong = self._run_after("edit", args)
        if wrong is not None:
            return wrong
        text = target.read_text(encoding="utf-8")
        old, new = _trim(args["old"]), _trim(args["new"])
        refused = _refusal(args["path"], text, old, new)
        if refused is not None:
            return self._failed("edit", refused[0], refused[1], args)
        lines = text.splitlines()
        want = old.split("\n")
        i = next(k for k in range(len(lines)) if lines[k : k + len(want)] == want)
        changed = lines[:i] + (new.split("\n") if new else []) + lines[i + len(want) :]
        after = "\n".join(changed) + ("\n" if text.endswith("\n") else "")
        from crew_org.session.tools import changed_lines  # noqa: PLC0415

        broken = ""
        if args["path"].endswith(".py"):
            error = _parse_error(after)
            if error is not None and _parse_error(text) is None:
                reply = (
                    f"Your changes have NOT been applied: `{args['path']}` would stop parsing "
                    f"({error[0]}, line {error[1]}).\n\nThe lines as they would have been:\n"
                    f"{changed_lines(text, after)}\n\nThe lines as they are:\n"
                    f"{changed_lines(text, after, side='old')}"
                )
                return self._failed("edit", "edit.parse_guard", reply, args)
            if error is not None:
                broken = f" It doesn't parse: {error[0]} on line {error[1]}."
        target.write_text(after, encoding="utf-8")
        said = f"Replaced lines in `{args['path']}`.{broken}\nIt now reads:\n"
        return self._then_run("edit", said + changed_lines(text, after), script)

    def _not_a_path(self, name: str, args: dict[str, Any], key: str) -> Judged:
        said = f"`{key}` is a file's path, of at most {MAX_PATH} characters on one line."
        return self._failed(name, "not_a_path", said, args)

    def _existing(self, name: str, args: dict[str, Any], key: str = "path") -> Judged | None:
        if not a_path(args[key]):
            return self._not_a_path(name, args, key)
        target = inside(self.directory, args[key])
        if target is None:
            return self._failed(name, "outside", "Only files inside the part's directory.", args)
        if not target.is_file():
            return self._failed(name, "no_file", f"There's no file {args[key]}.", args)
        return None

    def _run(self, args: dict[str, Any]) -> Judged:
        missing = self._existing("run", args)
        if missing is not None:
            return missing
        done = self.execute(["python", args["path"]], RUN_TIMEOUT)
        self.runs.append({"path": args["path"], "code": done.code, "seconds": done.seconds})
        if done.code == 0 and all((self.directory / o).is_file() for o in self.outputs):
            self.compiled = True
        reply = f"exit {done.code} after {done.seconds}s\n{done.output[-TAIL:]}"
        if done.code != 0 and self.arm == BASE:
            hinted = self.hint(done.output)
            reply += f"\n\n{hinted}" if hinted else ""
        return Judged("run", "ok", reply)

    def hint(self, output: str) -> str:
        """For a run's last AttributeError, where the name is (`hint.py`), or nothing."""
        found = list(NO_ATTRIBUTE.finditer(output))
        if not found:
            return ""
        last = found[-1]
        owner = last.group(1) or last.group(2) or last.group(3)
        done = self.execute(
            ["python", "-I", "-", owner, last.group(4)], LOOKUP_TIMEOUT, stdin=HINT_SOURCE
        )
        for line in reversed(done.output.splitlines()):
            if line.startswith(hint_module.MARK):
                said = json.loads(line[len(hint_module.MARK) :])
                return "" if "error" in said else hint_module.said(said)
        return ""

    def _inspect(self, args: dict[str, Any]) -> Judged:
        missing = self._existing("inspect", args)
        if missing is not None:
            return missing
        found = self.measure(args["path"])
        return Judged("inspect", "ok", json.dumps(found))

    def _skill(self, args: dict[str, Any]) -> Judged:
        offered = skills.registry(skills.for_arm(self.arm))
        found = offered.get(args["name"])
        if found is None:
            named = ", ".join(f"`{n}`" for n in offered)
            return self._failed("skill", "unknown", f"No skill `{args['name']}`: {named}.", args)
        return Judged("skill", "ok", found.body())

    def _lookup(self, args: dict[str, Any]) -> Judged:
        """`lookup.py` on the query, run from stdin in the container, as the measure is."""
        if not args["query"].strip() or len(args["query"]) > MAX_PATH:
            reply = f"`query` is a name or a fragment, of at most {MAX_PATH} characters."
            return self._failed("lookup", "not_a_query", reply, args)
        done = self.execute(
            ["python", "-I", "-", args["query"]], LOOKUP_TIMEOUT, stdin=LOOKUP_SOURCE
        )
        for line in reversed(done.output.splitlines()):
            if line.startswith(lookup_module.MARK):
                return Judged("lookup", "ok", line[len(lookup_module.MARK) :])
        self.troubles["lookup_unfinished"] = self.troubles.get("lookup_unfinished", 0) + 1
        return self._failed(
            "lookup", "unfinished", f"The lookup didn't finish (exit {done.code}).", args
        )

    def versions(self) -> dict[str, str | None]:
        """CadQuery's and OCP's versions in this container, or none if it can't say. A
        container already gone is the session's to end, as `workspace_gone`."""
        try:
            done = self.execute(["python", "-I", "-c", VERSIONS], LOOKUP_TIMEOUT)
        except Gone:
            return {"cadquery": None, "ocp": None}
        for line in reversed(done.output.splitlines()):
            if line.startswith(VERSIONS_MARK):
                found = json.loads(line[len(VERSIONS_MARK) :])
                return {"cadquery": found.get("cadquery"), "ocp": found.get("ocp")}
        return {"cadquery": None, "ocp": None}

    def _ending(self, name: str, args: dict[str, Any]) -> Judged:
        if name == "done":
            missing = self._existing("done", args, "script")
            if missing is not None:
                return missing
        return Judged(name, "ok", "", args=args)

    def execute(self, command: list[str], timeout: int, stdin: str | None = None) -> Any:
        done = self.workspace.exec(command, timeout=timeout, stdin=stdin)
        if getattr(self.workspace, "lost", False):
            raise Gone(done.output[-TAIL:])
        return done

    def measure(
        self, path: str, probes: list[Any] | None = None, mate: str | None = None
    ) -> dict[str, Any]:
        """What `measure.py` finds, run from stdin in the container, never from /work."""
        request = {"path": path, "probes": probes or [], "mate": mate}
        done = self.execute(
            ["python", "-I", "-", json.dumps(request)], MEASURE_TIMEOUT, stdin=MEASURE_SOURCE
        )
        for line in reversed(done.output.splitlines()):
            if line.startswith(measure.MARK):
                return json.loads(line[len(measure.MARK) :])
        self.troubles["measure_unfinished"] = self.troubles.get("measure_unfinished", 0) + 1
        return {"path": path, "error": f"the measure didn't finish (exit {done.code})"}

    def measure_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """`measure.py` on a whole request: the harder cases' `against`, `self`,
        `cylinders` and `section` beside the probes."""
        done = self.execute(
            ["python", "-I", "-", json.dumps(request)], MEASURE_TIMEOUT, stdin=MEASURE_SOURCE
        )
        for line in reversed(done.output.splitlines()):
            if line.startswith(measure.MARK):
                return json.loads(line[len(measure.MARK) :])
        self.troubles["measure_unfinished"] = self.troubles.get("measure_unfinished", 0) + 1
        return {"path": request["path"], "error": f"the measure didn't finish (exit {done.code})"}

    def final(self, script: str, probes: list[Any], mate: str | None) -> dict[str, Any]:
        """`done`'s script, run again from a clean start, and what it wrote, measured."""
        output = self.directory / OUTPUT
        output.unlink(missing_ok=True)
        ran = self.execute(["python", script], RUN_TIMEOUT)
        result: dict[str, Any] = {"script": script, "code": ran.code, "tail": ran.output[-TAIL:]}
        if ran.code != 0 or not output.is_file():
            result["measured"] = {"path": OUTPUT, "error": f"no {OUTPUT} after exit {ran.code}"}
            return result
        result["measured"] = self.measure(OUTPUT, probes, mate)
        return result

    def final_case(self, script: str, requests: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """`done`'s script, run again from a clean start, and each file it wrote, measured
        by its own request (`cad_eval/run.py` makes them from the case's members)."""
        for name in self.outputs:
            (self.directory / name).unlink(missing_ok=True)
        ran = self.execute(["python", script], RUN_TIMEOUT)
        result: dict[str, Any] = {"script": script, "code": ran.code, "tail": ran.output[-TAIL:]}
        measured: dict[str, Any] = {}
        for name, request in requests.items():
            written = (self.directory / request["path"]).is_file()
            if ran.code != 0 or not written:
                error = f"no {request['path']} after exit {ran.code}"
                if written:
                    error = f"exit {ran.code}: {request['path']} was written, but the script failed"
                measured[name] = {"path": request["path"], "error": error}
            else:
                measured[name] = self.measure_request(request)
        result["measured"] = measured
        return result
