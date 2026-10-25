"""Each repository check fails on a planted file and passes on a clean one."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[2] / "scripts"
# Built here, so the planted values never sit in a tracked file this repository's check reads.
ADDRESS = ".".join(["192", "168", "1", "20"])
HOST = "planted" + "-host"
ROW = {"suite": "benchmark", "case": "sprint-metrics-662", "calls": 3, "ending": "done"}


def check(tmp_path: Path, script: str, files: dict[str, str], hosts: str = "") -> tuple[int, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    (tmp_path / "hosts.env").write_text(hosts, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"INFRA_HOSTS": str(tmp_path / "hosts.env"), "PATH": "/usr/bin:/bin"},
    )
    return done.returncode, done.stdout


def test_numbers_pass(tmp_path: Path) -> None:
    code, out = check(tmp_path, "check_no_prompts.py", {"results/benchmark.jsonl": json.dumps(ROW)})
    assert code == 0, out


@pytest.mark.parametrize(
    ("files", "said"),
    [
        ({"results/benchmark.jsonl": json.dumps({**ROW, "prompt": "Fix it"})}, "declared field"),
        ({"results/benchmark.jsonl": json.dumps({**ROW, "ending": "it said so"})}, "short names"),
        ({"notes/run.jsonl": json.dumps(ROW)}, "outside results/"),
        ({"runs/x/start.md": "# start"}, "records are"),
        ({"notes.md": '{"role": "system", "content": "You are"}'}, "chat message"),
        ({"dump.json": '{"reasoning_content": "hm"}'}, "chat message"),
    ],
)
def test_text_where_numbers_belong_fails(tmp_path: Path, files: dict[str, str], said: str) -> None:
    code, out = check(tmp_path, "check_no_prompts.py", files)
    assert code == 1
    assert said in out


def test_an_address_fails(tmp_path: Path) -> None:
    code, out = check(tmp_path, "check_addresses.py", {"a.toml": f'url = "http://{ADDRESS}:30000"'})
    assert code == 1
    assert ADDRESS in out


def test_a_local_hosts_value_fails(tmp_path: Path) -> None:
    code, out = check(
        tmp_path,
        "check_addresses.py",
        {"a.md": f"reach {HOST} over ssh"},
        hosts=f"SPARK_ADDR={HOST}\n",
    )
    assert code == 1
    assert "INFRA_HOSTS" in out


def test_localhost_passes(tmp_path: Path) -> None:
    code, out = check(tmp_path, "check_addresses.py", {"a.toml": 'url = "http://localhost:4000"'})
    assert code == 0, out
