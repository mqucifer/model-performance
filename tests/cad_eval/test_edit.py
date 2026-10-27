"""`edit`, and `run` on `write` and `edit` (mqucifer/model-performance#40, A1).

`edit` is crew's `replace_text`, behaviour and all: whole lines, quoted once; a refusal
that says why (twice, part of a line, the closest block, already made); a Python file
that would stop parsing isn't changed; the reply shows the edited lines, numbered.
`write` and `edit` take `run`: `true` runs the file, a path runs that script, and a
refused edit runs nothing. A run's AttributeError says which classes have the name."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cad_eval import tools as t
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace, Ran

SCRIPT = """import cadquery as cq

part = cq.Workplane("XY").box(10, 10, 5)
part = part.faces(">Z").hole(3)
cq.exporters.export(part, "part.step")
"""


def tools(tmp_path: Path, script: str = SCRIPT, **fake: Any) -> PartTools:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "make.py").write_text(script)
    return PartTools(tmp_path, FakeWorkspace(directory=tmp_path, **fake), arm="base")


def edit(tool: PartTools, **args: Any) -> t.Judged:
    return tool.call("edit", json.dumps({"path": "make.py", **args}))


def test_whole_lines_quoted_once_are_replaced_and_shown_numbered(tmp_path: Path) -> None:
    tool = tools(tmp_path)
    found = edit(tool, old='part = part.faces(">Z").hole(3)', new='part = part.faces(">Z").hole(4)')
    assert found.outcome == "ok"
    assert "hole(4)" in (tmp_path / "make.py").read_text()
    assert '    4| part = part.faces(">Z").hole(4)' in found.reply
    # One leading and one trailing newline are forgiven, as crew's are.
    again = edit(
        tool, old='\npart = part.faces(">Z").hole(4)\n', new='part = part.faces(">Z").hole(5)'
    )
    assert again.outcome == "ok"


def test_lines_quoted_twice_are_refused_with_where(tmp_path: Path) -> None:
    tool = tools(tmp_path, SCRIPT + "x = 1\nx = 1\n")
    found = edit(tool, old="x = 1", new="x = 2")
    assert (found.outcome, found.why) == ("failed", "edit.twice")
    assert "2 times" in found.reply and "lines 6, 7" in found.reply
    assert (tmp_path / "make.py").read_text().count("x = 1") == 2


def test_part_of_a_line_is_refused_saying_which_line(tmp_path: Path) -> None:
    found = edit(tools(tmp_path), old="hole(3)", new="hole(4)")
    assert (found.outcome, found.why) == ("failed", "edit.part_of_a_line")
    assert "line 4" in found.reply


def test_lines_not_there_get_the_closest_block(tmp_path: Path) -> None:
    found = edit(tools(tmp_path), old='part = cq.Workplane("XY").box(10, 10, 6)', new="z = 0")
    assert (found.outcome, found.why) == ("failed", "edit.closest")
    assert (
        "line 3" in found.reply and '    3| part = cq.Workplane("XY").box(10, 10, 5)' in found.reply
    )


def test_a_change_already_made_and_nothing_close_are_said(tmp_path: Path) -> None:
    tool = tools(tmp_path)
    assert edit(tool, old="y = 7", new="import cadquery as cq").why == "edit.already"
    assert edit(tool, old="zzzz qqqq wwww", new="z = 0").why == "edit.not_found"
    assert edit(tool, old="x", new="x").why == "edit.same"
    assert edit(tool, old="  ", new="z = 0").why == "edit.empty"
    assert tool.call("edit", json.dumps({"path": "no.py", "old": "a", "new": "z"})).why == (
        "edit.no_file"
    )


def test_an_edit_that_would_stop_a_python_file_parsing_isnt_applied(tmp_path: Path) -> None:
    tool = tools(tmp_path)
    found = edit(tool, old="import cadquery as cq", new="import cadquery as (")
    assert (found.outcome, found.why) == ("failed", "edit.parse_guard")
    assert "NOT been applied" in found.reply
    assert (tmp_path / "make.py").read_text() == SCRIPT
    # A file that already doesn't parse can be edited, and the reply says so.
    broken = tools(tmp_path / "b", "x = (\ny = 1\n")
    found = edit(broken, old="y = 1", new="y = 2")
    assert found.outcome == "ok" and "doesn't parse" in found.reply


def test_run_true_runs_the_file_just_written_or_edited(tmp_path: Path) -> None:
    tool = tools(tmp_path, writes={"part.step": "step"})
    found = tool.call("write", json.dumps({"path": "make.py", "content": SCRIPT, "run": True}))
    assert found.outcome == "ok"
    assert tool.workspace.commands[-1] == ["python", "make.py"]
    assert "exit 0" in found.reply
    # A first compiling part counts on a write's run as on `run`'s.
    assert tool.compiled
    found = edit(
        tool, old='part = part.faces(">Z").hole(3)', new='part = part.faces(">Z").hole(4)', run=True
    )
    assert found.outcome == "ok" and "exit 0" in found.reply


def test_run_may_name_another_script(tmp_path: Path) -> None:
    tool = tools(tmp_path)
    (tmp_path / "params.py").write_text("SIZE = 10\n")
    found = tool.call(
        "edit",
        json.dumps({"path": "params.py", "old": "SIZE = 10", "new": "SIZE = 12", "run": "make.py"}),
    )
    assert found.outcome == "ok"
    assert tool.workspace.commands[-1] == ["python", "make.py"]


def test_a_refused_edit_runs_nothing(tmp_path: Path) -> None:
    tool = tools(tmp_path)
    before = len(tool.workspace.commands)
    found = edit(tool, old="hole(3)", new="hole(4)", run=True)
    assert found.outcome == "failed"
    assert len(tool.workspace.commands) == before


def test_run_false_or_absent_runs_nothing_and_a_bad_run_is_said(tmp_path: Path) -> None:
    tool = tools(tmp_path)
    tool.call("write", json.dumps({"path": "a.py", "content": "x = 1\n", "run": False}))
    tool.call("write", json.dumps({"path": "b.py", "content": "x = 1\n"}))
    assert tool.workspace.commands == []
    found = tool.call("write", json.dumps({"path": "c.py", "content": "x = 1\n", "run": 3}))
    assert (found.outcome, found.why) == ("failed", "not_a_run")
    assert (tmp_path / "c.py").exists() is False
    missing = tool.call("write", json.dumps({"path": "d.py", "content": "x\n", "run": "no.py"}))
    assert missing.why == "no_file"


class Failing(FakeWorkspace):
    """A run that raises `error`, and a lookup index that knows where names are."""

    error: str = ""

    def exec(self, command: list[str], timeout: int = 0, stdin: str | None = None) -> Ran:
        if command[:2] == ["python", "make.py"]:
            self.commands.append(command)
            return Ran("run", 1, f"Traceback (most recent call last):\n  ...\n{self.error}")
        return super().exec(command, timeout, stdin)


def test_an_attribute_error_says_which_classes_have_the_name(tmp_path: Path) -> None:
    (tmp_path / "make.py").write_text(SCRIPT)
    workspace = Failing(directory=tmp_path)
    workspace.error = "AttributeError: 'Workplane' object has no attribute 'isValid'"
    tool = PartTools(tmp_path, workspace, arm="base")
    found = tool.call("run", json.dumps({"path": "make.py"}))
    assert found.outcome == "ok"
    assert "`isValid` isn't on Workplane. It's on: cq.Shape" in found.reply


def test_a_name_no_class_has_gets_the_nearest_names(tmp_path: Path) -> None:
    (tmp_path / "make.py").write_text(SCRIPT)
    workspace = Failing(directory=tmp_path)
    workspace.error = "AttributeError: type object 'Face' has no attribute 'makeFace'"
    tool = PartTools(tmp_path, workspace, arm="base")
    found = tool.call("run", json.dumps({"path": "make.py"}))
    assert "No CadQuery class has `makeFace`. Names near it:" in found.reply
    assert "makeFromWires" in found.reply


def test_the_v1_tools_are_unchanged(tmp_path: Path) -> None:
    names = [s["function"]["name"] for s in PartTools(tmp_path, FakeWorkspace()).specs]
    assert names == ["write", "run", "inspect", "done", "blocked"]
    assert t.SPECS[0]["function"]["parameters"]["required"] == ["path", "content"]
    assert "run" not in t.SPECS[0]["function"]["parameters"]["properties"]
