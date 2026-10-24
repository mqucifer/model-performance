"""The command line, and the dry run end to end: every step printed, nothing run."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from swap import cli, core, runners

from .conftest import FIXTURES

REAL_TICKS = runners.ticks_running
REAL_INFRA_COMMIT = cli.infra_commit


@pytest.fixture
def infra(tmp_path: Path) -> Path:
    launch = tmp_path / "compose/spark/sglang/compose.yaml"
    launch.parent.mkdir(parents=True)
    launch.write_text((FIXTURES / "compose.yaml").read_text())
    return tmp_path


@pytest.fixture(autouse=True)
def nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here starts ssh, the command, or a request: the real runner can't be built."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a dry run ran something: {args}")

    monkeypatch.setattr(runners.RealRunner, "__init__", refuse)
    monkeypatch.setattr(cli, "infra_commit", lambda infra_dir: "abc1234")
    monkeypatch.setattr(runners, "ticks_running", lambda: False)


def test_dry_run_prints_every_step_in_order(
    infra: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["Qwen/Qwen3.8-8B", "--dry-run", "--infra-dir", str(infra), "--", "bench", "-x"]
    code = cli.main(argv)
    assert code == 0
    err = capsys.readouterr().err
    expected = [
        "[dry-run] ssh $SPARK_USER@$SPARK_ADDR: true",
        "model=crew-local",
        "has crew-candidate",
        "swap 1/3: stop the 27B",
        "docker stop qwen3.8-27b-sglang",
        "swap 2/3: start Qwen/Qwen3.8-8B",
        "MODEL_PATH=Qwen/Qwen3.8-8B SERVED_MODEL_NAME=crew-candidate-sglang SPECULATIVE_ARGS=''",
        "up -d   < compose/spark/sglang/compose.yaml",
        "swap 3/3: wait until crew-candidate answers",
        "model=crew-candidate",
        "[dry-run] bench -x",
        "restore 1/3: remove the candidate",
        "restore 2/3: bring the 27B back (start-dflash)",
        "./start-dflash.sh",
        "restore 3/3: wait until crew-local answers",
        "the 27B answers again; exiting 0",
    ]
    position = 0
    for line in expected:
        found = err.find(line, position)
        assert found >= 0, f"missing, or out of order: {line}"
        position = found + len(line)
    assert "8888" not in err


def test_dry_run_refuses_while_a_tick_runs(
    infra: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runners, "ticks_running", lambda: True)
    code = cli.main(["m", "--dry-run", "--infra-dir", str(infra), "--", "bench"])
    assert code == core.REFUSED
    assert "tick is running" in capsys.readouterr().err


def test_missing_infra_record_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["m", "--dry-run", "--infra-dir", str(tmp_path), "--", "x"]) == core.REFUSED
    assert "mqucifer/infra#40" in capsys.readouterr().err


def test_real_run_without_the_spark_address_is_refused(
    infra: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hosts = tmp_path / "hosts.env"
    hosts.write_text("# no values yet\n")
    code = cli.main(["m", "--infra-dir", str(infra), "--hosts", str(hosts), "--", "x"])
    assert code == core.REFUSED
    assert "SPARK_ADDR, SPARK_USER not set" in capsys.readouterr().err


def test_the_commands_own_options_stay_its_own() -> None:
    args = cli.parse(["m", "--dry-run", "--", "bench", "--dry-run", "--", "-x"])
    assert args.dry_run is True
    assert args.command == ["bench", "--dry-run", "--", "-x"]


@pytest.mark.parametrize("argv", [["m"], ["m", "--"], ["two words", "--", "x"]])
def test_bad_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse(argv)


@pytest.mark.parametrize(
    ("command_line", "is_tick"),
    [
        ("uv run crew tick --repo sprint-metrics", True),
        ("/u/crew/.venv/bin/python /u/crew/.venv/bin/crew tick --repo x", True),
        ("/u/.local/bin/uv run --directory /u/crew crew tick", True),
        ("crew tick", True),
        ('/bin/zsh -c while pgrep -f "bin/crew tick" >/dev/null; do sleep 15; done', False),
        ("/u/.venv/bin/python /u/.venv/bin/swap m -- crew tick", False),
        (f"pgrep -f {runners.TICK_PATTERN}", False),
        ("uv run crew ticker", False),
        ("uv run crew status", False),
    ],
)
def test_tick_pattern_matches_a_tick_and_nothing_that_mentions_one(
    command_line: str, is_tick: bool
) -> None:
    """pgrep -f takes an extended regex; this one reads the same in Python's re."""
    import re

    assert bool(re.search(runners.TICK_PATTERN, command_line)) is is_tick


@pytest.mark.parametrize(("others", "running"), [("", False), ("4242\n", True)])
def test_tick_check_ignores_this_process(
    monkeypatch: pytest.MonkeyPatch, others: str, running: bool
) -> None:
    import os

    found = f"{os.getpid()}\n{os.getppid()}\n{others}"
    done = subprocess.CompletedProcess([], 0, stdout=found, stderr="")
    monkeypatch.setattr(runners.subprocess, "run", lambda *a, **k: done)
    assert REAL_TICKS() is running


def test_infra_commit_names_the_launchs_commit(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "compose.yaml").write_text("name: x\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x")
    assert REAL_INFRA_COMMIT(tmp_path).isalnum()
    (tmp_path / "compose.yaml").write_text("name: y\n")
    assert REAL_INFRA_COMMIT(tmp_path).endswith("with local changes")
    assert REAL_INFRA_COMMIT(tmp_path / "missing") == "unknown"
