"""A case's fetched inputs from the captured copies only (mqucifer/model-performance#32):
checked by sha256, refused when missing, placed as the repository's setup would, and
never fetched by the case's setup."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from benchmark import inputs
from benchmark.cases import CASES, record
from common.config import load
from tests.benchmark.test_replay import BLOCKED, answer, run

TAG = "delivery-history-2026-10-16-2"


def archive(tag: str = TAG) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        body = json.dumps({"sprints": []}).encode()
        info = tarfile.TarInfo(f"{tag}/delivery-history.json")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    return data.getvalue()


def capture(tmp_path: Path, name: str, blobs: dict[str, tuple[str, bytes]]) -> Any:
    """A manifest giving `name` these inputs: {input: (pin, bytes)}."""
    import hashlib  # noqa: PLC0415

    settings = load(home=tmp_path)
    root = settings.records_dir / "inputs"
    (root / "blobs").mkdir(parents=True, exist_ok=True)
    entries = []
    for kind, (pin, body) in blobs.items():
        digest = hashlib.sha256(body).hexdigest()
        (root / "blobs" / digest).write_bytes(body)
        entries.append({"input": kind, "pin": pin, "sha256": digest})
    path = root / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {"cases": {}}
    manifest["cases"][name] = entries
    path.write_text(json.dumps(manifest))
    return settings


def test_a_case_whose_inputs_are_captured_gets_them_checked(tmp_path: Path) -> None:
    settings = capture(
        tmp_path,
        "crew-presentation-124",
        {"delivery-history": (TAG, archive()), "design-system-css": ("v0.1.0", b"css")},
    )
    manifest_sha, found = inputs.for_case(settings, "crew-presentation-124")
    assert [i.input for i in found] == ["delivery-history", "design-system-css"]
    assert len(manifest_sha) == 64
    fields = inputs.row_fields(manifest_sha, found)
    assert fields["input_delivery_history"] == found[0].sha256
    assert fields["input_design_system_css"] == found[1].sha256


@pytest.mark.parametrize("damage", ["no_manifest", "not_listed", "no_blob", "changed"])
def test_a_missing_or_changed_input_is_refused_saying_which(tmp_path: Path, damage: str) -> None:
    settings = capture(tmp_path, "crew-presentation-124", {"delivery-history": (TAG, archive())})
    root = settings.records_dir / "inputs"
    blob = next((root / "blobs").iterdir())
    name = "crew-presentation-124"
    if damage == "no_manifest":
        (root / "manifest.json").unlink()
    elif damage == "not_listed":
        name = "crew-presentation-83"
    elif damage == "no_blob":
        blob.unlink()
    else:
        blob.write_bytes(b"something else")
    with pytest.raises(inputs.InputMissing) as refused:
        inputs.for_case(settings, name)
    said = str(refused.value)
    assert {
        "no_manifest": "is missing",
        "not_listed": "never captured",
        "no_blob": "no blob",
        "changed": "hashes to",
    }[damage] in said


def test_the_inputs_go_where_the_repositorys_setup_puts_them_and_out_of_git(tmp_path: Path) -> None:
    settings = capture(
        tmp_path,
        "crew-presentation-124",
        {"delivery-history": (TAG, archive()), "design-system-css": ("v0.1.0", b"css")},
    )
    _, found = inputs.for_case(settings, "crew-presentation-124")
    root = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    inputs.place(root, found)
    assert (root / ".package" / TAG / "delivery-history.json").is_file()
    assert (root / ".package" / "design-system-v0.1.0.css").read_bytes() == b"css"
    assert (root / ".benchmark" / "setup.py").is_file()
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True
    )
    assert status.stdout == ""  # neither the inputs nor the setup can be committed


def test_a_worktrees_exclude_is_its_shared_git_dirs(tmp_path: Path) -> None:
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        check=True,
    )
    tree = tmp_path / "tree"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "--detach", str(tree)], check=True
    )
    settings = capture(tmp_path, "crew-presentation-124", {"design-system-css": ("v0.1.0", b"css")})
    _, found = inputs.for_case(settings, "crew-presentation-124")
    inputs.place(tree, found)
    status = subprocess.run(
        ["git", "-C", str(tree), "status", "--porcelain"], capture_output=True, text=True
    )
    assert status.stdout == ""


@pytest.mark.parametrize("name", ["crew-presentation-124", "crew-presentation-83"])
def test_no_cases_setup_fetches_a_release_or_the_css(name: str) -> None:
    """The record's setup runs the benchmark's script, which downloads nothing."""
    given = record(CASES[name])
    assert given is not None and inputs.REPO_SETUP in given
    fake = [inputs.Input("design-system-css", "v0.1.0", "0" * 64, Path("x"))]
    changed = inputs.setup_record(given, fake)
    assert (
        inputs.SETUP in changed
        and "tools/setup.py" not in changed.split("setup:", 1)[1].splitlines()[0]
    )
    assert changed.replace(inputs.SETUP, inputs.REPO_SETUP) == given  # nothing else changes
    for host in ("github.com", "jsdelivr", "urlopen", "urllib"):
        assert host not in inputs.SETUP_SCRIPT


def test_a_case_with_no_inputs_keeps_its_own_setup() -> None:
    given = record(CASES["sprint-metrics-662"])
    assert inputs.setup_record(given, []) == given


def test_the_benchmarks_setup_runs_with_no_network_and_calls_only_the_dependencies(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / ".package").mkdir()
    (root / ".package" / "x").write_text("in place")
    (root / "tools" / "setup.py").write_text(
        "from pathlib import Path\n"
        "import urllib.request\n"
        "def _sync_dependencies():\n"
        "    Path(__file__).with_name('synced').write_text('yes')\n"
        "def _download_delivery_history(tag):\n    raise SystemExit('fetched a release')\n"
        "def _download_design_system_css(v):\n    raise SystemExit('fetched the css')\n"
    )
    (root / ".benchmark").mkdir()
    (root / ".benchmark" / "setup.py").write_text(inputs.SETUP_SCRIPT)
    guard = (
        "import socket, runpy, sys\n"
        "def refuse(*a, **k):\n    raise OSError('no network in this test')\n"
        "socket.socket.connect = refuse\nsocket.create_connection = refuse\n"
        f"runpy.run_path({str(root / '.benchmark' / 'setup.py')!r}, run_name='__main__')\n"
    )
    done = subprocess.run([sys.executable, "-c", guard], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (root / "tools" / "synced").read_text() == "yes"
    assert "captured copies" in done.stdout


def test_a_replay_records_its_inputs_and_refuses_a_case_without_them(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, _, _ = run(tmp_path, repo, [answer(BLOCKED)], monkeypatch=monkeypatch)
    assert len(row["inputs_manifest"]) == 64 and row["input_delivery_history"] is None
    # A home whose records hold no captured inputs: the case is refused, never fetched.
    bare = tmp_path / "bare"
    bare.mkdir()
    row, made, _ = run(bare, repo, [answer(BLOCKED)], monkeypatch=monkeypatch)
    assert (row["ending"], row["stop"]) == ("refused", "input_missing")
    assert made == []  # refused before any container
