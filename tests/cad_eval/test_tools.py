"""Each tool call judged in BFCL's categories: well formed (AST), then done as asked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_eval.tools import PartTools, inside
from tests.cad_eval.fakes import FakeWorkspace


@pytest.fixture
def tools(tmp_path: Path) -> PartTools:
    return PartTools(tmp_path, FakeWorkspace(directory=tmp_path))


@pytest.mark.parametrize(
    ("name", "raw", "rule"),
    [
        ("draw", '{"path": "a.py"}', "session.arguments"),  # no such tool
        ("write", "not json", "session.arguments"),  # not an object
        ("write", '["a.py"]', "session.arguments"),
        ("write", '{"path": "a.py"}', "session.arguments"),  # missing `content`
        ("run", '{"path": "a.py", "timeout": 5}', "session.arguments"),  # unknown argument
    ],
)
def test_a_call_crews_argument_rule_refuses_is_malformed(
    tools: PartTools, name: str, raw: str, rule: str
) -> None:
    judged = tools.call(name, raw)
    assert (judged.outcome, judged.why) == ("malformed", rule)
    assert judged.reply  # the model is told why


def test_a_value_of_the_wrong_type_is_ill_typed(tools: PartTools) -> None:
    judged = tools.call("write", json.dumps({"path": "a.py", "content": 7}))
    assert judged.outcome == "ill_typed"
    assert not (tools.directory / "a.py").exists()


@pytest.mark.parametrize("path", ["/etc/passwd", "../a.py", "a/../../b.py", ".crew-home/x", ""])
def test_a_path_out_of_the_parts_directory_fails(tools: PartTools, path: str) -> None:
    assert tools.call("write", json.dumps({"path": path, "content": "x"})).outcome == "failed"
    assert inside(tools.directory, path) is None


def test_a_file_that_isnt_there_fails(tools: PartTools) -> None:
    for name, args in (("run", {"path": "a.py"}), ("inspect", {"path": "part.step"})):
        assert tools.call(name, json.dumps(args)).why == "no_file"
    assert tools.call("done", '{"script": "a.py"}').outcome == "failed"


def test_too_much_content_fails(tools: PartTools) -> None:
    judged = tools.call("write", json.dumps({"path": "a.py", "content": "x" * 200_001}))
    assert judged.why == "too_large"


def test_a_script_that_raises_is_still_a_run_that_did_what_it_asked(tools: PartTools) -> None:
    tools.workspace.exits = [1]
    assert tools.call("write", '{"path": "a.py", "content": "raise SystemExit(1)"}').outcome == "ok"
    judged = tools.call("run", '{"path": "a.py"}')
    assert judged.outcome == "ok"
    assert judged.reply.startswith("exit 1")
    assert tools.runs == [{"path": "a.py", "code": 1, "seconds": 0.1}]


def test_arguments_may_come_as_an_object(tools: PartTools) -> None:
    assert tools.call("write", {"path": "a.py", "content": ""}).outcome == "ok"


def test_inspect_runs_the_measure_from_stdin_never_from_the_parts_directory(
    tools: PartTools,
) -> None:
    (tools.directory / "part.step").write_text("x")
    tools.workspace.measured = {"valid": True}
    judged = tools.call("inspect", '{"path": "part.step"}')
    assert json.loads(judged.reply) == {"path": "part.step", "valid": True}
    assert tools.workspace.commands[-1][:3] == ["python", "-I", "-"]
    assert sorted(p.name for p in tools.directory.iterdir()) == ["part.step"]


def test_final_runs_the_script_again_from_a_clean_start(tools: PartTools) -> None:
    (tools.directory / "part.py").write_text("")
    (tools.directory / "part.step").write_text("stale")
    tools.workspace.exits = [1]
    result = tools.final("part.py", [], None)
    assert result["code"] == 1
    assert "error" in result["measured"]
    assert not (tools.directory / "part.step").exists()
