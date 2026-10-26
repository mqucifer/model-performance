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

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cad_eval import lookup as lookup_module
from cad_eval import measure, skills

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
# A measure that the tool itself failed: not the model's query, not its part.
TOOL_FAILURES = ("the measure didn't finish", "it loads but can't be measured")
# The arms (mqucifer/model-performance#21): what each adds to the session's tools.
ARMS = tuple(skills.ARMS)


def _spec(name: str, description: str, **properties: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    k: {"type": "string", "description": v} for k, v in properties.items()
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
    measure_spec = _spec(
        "measure",
        "Measure your part, in the container: `hole x,y,z` (the hole nearest a point: its "
        "diameter and axis), `distance A B` (between two faces), `clearance FILE` (to "
        "another of your STEP files: overlap and gap), or `position A` (where faces are). "
        "A face is a selector such as `>Z`, `<X`, `%CYLINDER`, or a point `x,y,z`.",
        path="The STEP file to measure, relative to the part's directory.",
        query="What to measure, such as `hole 0,0,5` or `distance >Z <Z`.",
    )
    _, lookup, tools = skills.ARMS[arm]
    found_specs = [SKILL_SPEC, found] if lookup else [SKILL_SPEC]
    return found_specs + ([measure_spec] if "measure" in tools else [])


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
    ) -> None:
        self.directory = directory
        self.workspace = workspace
        self.outputs = outputs or [OUTPUT]
        self.arm = arm
        self.specs = specs_for(self.outputs) + (arm_specs(arm) if arm else [])
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
        return getattr(self, f"_{name}")(args)

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
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
        except OSError as exc:
            return self._failed("write", "not_written", f"It couldn't be written: {exc}", args)
        return Judged("write", "ok", f"Wrote {args['path']} ({len(args['content'])} characters).")

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
        return Judged("run", "ok", f"exit {done.code} after {done.seconds}s\n{done.output[-TAIL:]}")

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
