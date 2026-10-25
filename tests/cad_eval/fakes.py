"""A workspace that runs nothing: each command gets the next scripted result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cad_eval import measure


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
        self.commands.append(command)
        if command[:3] == ["python", "-I", "-"]:
            import json  # noqa: PLC0415

            path = json.loads(command[3])["path"]
            found = self.measured_by.get(path, self.measured)
            return Ran("measure", 0, measure.MARK + json.dumps({"path": path, **found}))
        code = self.exits.pop(0) if self.exits else 0
        if code == 0 and self.directory is not None:
            for name, text in self.writes.items():
                (self.directory / name).write_text(text)
        return Ran(" ".join(command), code, "Traceback: boom" if code else "ok")
