"""No tool touches a file outside the part's directory, even through a link (the second
review of #41): a symlink the model makes from a `run`, in the container, resolves on
the host, so `read` could read, and `write` overwrite, a host file such as the cases'
answer key. Every host-side path is resolved, and any link is refused."""

from __future__ import annotations

import json
import shutil
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


def test_a_path_of_dot_or_a_case_folded_crew_home_is_refused(setup) -> None:
    """The final review of #41: `.` raised an IndexError, which ended the run."""
    tools, _, _ = setup
    for path in (".", "./", ".CREW-HOME/x"):
        assert tools.call("read", json.dumps({"path": path})).outcome == "failed", path
        assert tools.call("write", json.dumps({"path": path, "content": "x"})).outcome == "failed"


@pytest.mark.parametrize("swap", ["file", "folder"])
def test_a_link_swapped_in_during_reads_and_writes_never_reaches_outside(
    tmp_path: Path, swap: str
) -> None:
    """The race the final review of #41 won: a process flipping a file (or a folder) and
    a link to the outside, between the name's check and its use. Opened one component at
    a time with no following, no read returns the outside's text and no write lands
    there, however the flips fall."""
    import os  # noqa: PLC0415
    import threading  # noqa: PLC0415

    part = tmp_path / "part"
    part.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "a.py").write_text("ANSWER = 42\n")
    tools = PartTools(part, FakeWorkspace(directory=part), arm="base")
    tools.plan_passed = True
    path = "a.py" if swap == "file" else "d/a.py"
    name = part / ("a.py" if swap == "file" else "d")
    stop = threading.Event()

    def flip() -> None:
        target = outside / "a.py" if swap == "file" else outside
        while not stop.is_set():
            try:
                if name.is_symlink() or name.is_file():
                    name.unlink()
                elif name.is_dir():
                    shutil.rmtree(name)
                if swap == "file":
                    name.write_text("mine = 1\n")
                else:
                    name.mkdir()
                    (name / "a.py").write_text("mine = 1\n")
                if swap == "folder":
                    shutil.rmtree(name)
                os.symlink(target, name)
            except OSError:
                pass

    flipper = threading.Thread(target=flip, daemon=True)
    flipper.start()
    seen = set()
    try:
        for k in range(3000):
            read = tools.call("read", json.dumps({"path": path}))
            assert "ANSWER" not in read.reply
            seen.add(read.why or read.outcome)
            tools.call("write", json.dumps({"path": path, "content": f"W = {k}\n"}))
            assert (outside / "a.py").read_text() == "ANSWER = 42\n"
    finally:
        stop.set()
        flipper.join(timeout=5)
    # The race ran: reads met the real file, and met it gone or a link.
    assert "ok" in seen and len(seen) > 1, seen


@pytest.mark.parametrize("path", ["key.py", "out/cases.py"])
def test_the_open_itself_refuses_a_link_when_the_check_has_been_raced(
    setup, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The race's losing side, made certain: the name's check passes (as it did before
    the swap), and the open still refuses the link, to a file or through a folder."""
    from cad_eval import tools as tools_module  # noqa: PLC0415

    tools, part, outside = setup
    monkeypatch.setattr(tools_module, "inside", lambda directory, p: directory / p)
    read = tools.call("read", json.dumps({"path": path}))
    assert read.why == "outside" and "ANSWER" not in read.reply
    write = tools.call("write", json.dumps({"path": path, "content": "ANSWER = 0\n"}))
    assert write.why == "outside"
    edit = tools.call("edit", json.dumps({"path": path, "old": "ANSWER = 42", "new": "x"}))
    assert edit.outcome == "failed"
    assert (outside / "cases.py").read_text() == "ANSWER = 42\n"
