"""No tool touches a file outside the part's directory, even through a link (the second
review of #41): a symlink the model makes from a `run`, in the container, resolves on
the host, so `read` could read, and `write` overwrite, a host file such as the cases'
answer key. Every host-side path is resolved, and any link is refused."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_eval import run as cad
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace


@pytest.fixture
def setup(tmp_path: Path) -> tuple[PartTools, Path, Path]:
    part = tmp_path / "part"
    part.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "cases.py").write_text("ANSWER = 42\n")
    (part / "make.py").write_text("x = 1\n")
    # What a `run` in the container could make: a link to a file, and to a folder.
    (part / "key.py").symlink_to(outside / "cases.py")
    (part / "out").symlink_to(outside)
    tools = PartTools(part, FakeWorkspace(directory=part), arm="base")
    tools.plan_passed = True
    return tools, part, outside


def test_read_refuses_a_link_out_to_a_file_or_through_a_folder(setup) -> None:
    tools, _, _ = setup
    for path in ("key.py", "out/cases.py"):
        found = tools.call("read", json.dumps({"path": path}))
        assert found.outcome == "failed" and found.why == "outside", path
        assert "ANSWER" not in found.reply


def test_write_and_edit_refuse_to_go_out_through_a_link(setup) -> None:
    tools, _, outside = setup
    for path in ("key.py", "out/cases.py", "out/new.py"):
        found = tools.call("write", json.dumps({"path": path, "content": "ANSWER = 0\n"}))
        assert found.outcome == "failed" and found.why == "outside", path
    found = tools.call("edit", json.dumps({"path": "key.py", "old": "ANSWER = 42", "new": "x"}))
    assert found.outcome == "failed"
    assert (outside / "cases.py").read_text() == "ANSWER = 42\n"
    assert not (outside / "new.py").exists()


def test_run_done_and_run_script_refuse_a_link(setup) -> None:
    tools, _, _ = setup
    assert tools.call("run", json.dumps({"path": "key.py"})).why == "outside"
    assert tools.call("done", json.dumps({"script": "key.py"})).why == "outside"
    args = {"path": "a.py", "content": "y = 1\n", "run_script": "key.py"}
    assert tools.call("write", json.dumps(args)).why == "outside"


def test_files_inside_still_work(setup) -> None:
    tools, part, _ = setup
    assert tools.call("read", json.dumps({"path": "make.py"})).outcome == "ok"
    (part / "sub").mkdir()
    found = tools.call("write", json.dumps({"path": "sub/b.py", "content": "z = 1\n"}))
    assert found.outcome == "ok" and (part / "sub" / "b.py").read_text() == "z = 1\n"


def test_the_records_never_copy_through_a_link(setup, tmp_path: Path) -> None:
    _, part, _ = setup
    out = tmp_path / "records"
    cad.keep(part, out)
    kept = {p.relative_to(out / "files").as_posix() for p in (out / "files").rglob("*")}
    assert "make.py" in kept
    assert not any(name.startswith(("key.py", "out")) for name in kept)
    assert "ANSWER" not in "".join(p.read_text() for p in (out / "files").rglob("*") if p.is_file())
