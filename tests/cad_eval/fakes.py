"""A workspace that runs nothing: each command gets the next scripted result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cad_eval import measure

# A few of the lookup index's entries, as `hint.py` reads them in the image.
HINT_INDEX = [
    {"name": "cq.Shape.isValid", "on": ["cq.Compound", "cq.Shape", "cq.Solid"]},
    {"name": "cq.Workplane.union", "on": ["cq.Workplane"]},
    {"name": "cq.Face.makeFromWires", "on": ["cq.Face"]},
    {"name": "cq.Face.makeNSidedSurface", "on": ["cq.Face"]},
]


@dataclass
class Ran:
    command: str
    code: int
    output: str
    seconds: float = 0.1

    @property
    def ok(self) -> bool:
        return self.code == 0


@dataclass
class FakeWorkspace:
    # What `measure.py` reports, and what each `python <script>` run exits with.
    measured: dict[str, Any] = field(default_factory=dict)
    # A harder case's: what each member's file measures, by its path.
    measured_by: dict[str, dict[str, Any]] = field(default_factory=dict)
    exits: list[int] = field(default_factory=list)
    writes: dict[str, str] = field(default_factory=dict)
    directory: Any = None
    commands: list[list[str]] = field(default_factory=list)
    lost: bool = False
    started: bool = False
    stopped: bool = False
    start_ok: bool = True

    def start(self) -> Ran:
        self.started = True
        return Ran("start", 0 if self.start_ok else 125, "" if self.start_ok else "no image")

    def stop(self) -> None:
        self.stopped = True

    def exec(self, command: list[str], timeout: int = 0, stdin: str | None = None) -> Ran:
        if stdin and "CAD_EVAL_REAPED" in stdin:
            # The reap after each run, counted apart from the commands it follows.
            self.reaps = getattr(self, "reaps", 0) + 1
            left, still = getattr(self, "left", 0), getattr(self, "still", 0)
            return Ran("reap", 0, f"CAD_EVAL_REAPED {left} {still}")
        self.commands.append(command)
        self.timeouts = [*getattr(self, "timeouts", []), timeout]
        if command[:3] == ["python", "-I", "-c"] and "CAD_EVAL_VERSIONS" in command[3]:
            import json  # noqa: PLC0415

            found = {"cadquery": "2.8.0", "ocp": "7.9.3.1.1"}
            return Ran("versions", 0, "CAD_EVAL_VERSIONS " + json.dumps(found))
        if command[:3] == ["python", "-I", "-"] and stdin and "CAD_EVAL_SEARCH" in stdin:
            import json  # noqa: PLC0415

            asked = json.loads(command[3])
            found = {"query": asked["query"], "matches": 0, "page": 1, "pages": 1, "found": []}
            return Ran("search", 0, "CAD_EVAL_SEARCH " + json.dumps(found))
        if command[:3] == ["python", "-I", "-"] and stdin and "CAD_EVAL_HINT" in stdin:
            import json  # noqa: PLC0415

            from cad_eval import hint  # noqa: PLC0415

            found = hint.find(HINT_INDEX, command[3], command[4])
            return Ran("hint", 0, hint.MARK + json.dumps(found))
        if command[:3] == ["python", "-I", "-"] and stdin and "CAD_EVAL_LOOKUP" in stdin:
            import json  # noqa: PLC0415

            found = {"query": command[3], "matches": 1, "found": [{"name": "cq.Wire.makeHelix"}]}
            return Ran("lookup", 0, "CAD_EVAL_LOOKUP " + json.dumps(found))
        if command == ["python", "-I", "-"] and stdin and measure.MARK in stdin:
            import ast  # noqa: PLC0415
            import json  # noqa: PLC0415

            # The request, as the call after the source (`tools.measure_stdin`).
            call = stdin.rstrip().rsplit("\n", 1)[-1]
            asked = json.loads(ast.literal_eval(call[len("main(") : -1]))
            self.requests = [*getattr(self, "requests", []), asked]
            path = asked["path"]
            found = self.measured_by.get(path, self.measured)
            return Ran("measure", 0, measure.MARK + json.dumps({"path": path, **found}))
        code = self.exits.pop(0) if self.exits else 0
        if code == 0 and self.directory is not None:
            for name, text in self.writes.items():
                (self.directory / name).write_text(text)
        return Ran(" ".join(command), code, "Traceback: boom" if code else "ok")
