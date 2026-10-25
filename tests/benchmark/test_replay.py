"""One replay end to end against crew's real session, with a scripted model and a fake
container: every ending leaves a row of numbers and its records, and nothing behind."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from crew_org.tools import workspace as crew_workspace

from benchmark import replay as bench
from benchmark.cases import Case
from common.config import load
from common.litellm import Sender

CASE = Case("sprint-metrics", 662, "", "2026-10-17T19:27:26Z", "a test case")


@dataclass
class Ran:
    command: str
    code: int = 0
    output: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code == 0


class FakeWorkspace:
    """The held container's interface, running nothing."""

    def __init__(self, root: Path, start_code: int = 0) -> None:
        self.tools = crew_workspace.toolchain(root)
        self.start_code = start_code
        self.stopped = False

    def start(self) -> Ran:
        return Ran("start", self.start_code, "no engine" if self.start_code else "")

    def setup(self, timeout: int = 0) -> Ran | None:
        return None

    def resync(self, timeout: int = 0) -> Ran | None:
        return None

    def exec(self, command: list[str], timeout: int = 0, stdin: str | None = None) -> Ran:
        return Ran(" ".join(command))

    def stop(self) -> None:
        self.stopped = True


def call(name: str, arguments: str) -> dict[str, Any]:
    return {
        "id": f"c-{name}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def answer(*tool_calls: dict[str, Any], content: str = "") -> dict[str, Any]:
    message = {"role": "assistant", "content": content, "tool_calls": list(tool_calls) or None}
    return {
        "id": "r",
        "choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050},
    }


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "clone"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        [*git[:3], "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return path, base


def run(
    tmp_path: Path,
    repo: tuple[Path, str],
    answers: list[dict[str, Any]],
    *,
    cap: int = 10,
    start_code: int = 0,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], list[FakeWorkspace], Path]:
    clone, base = repo
    case = Case(CASE.repo, CASE.card, base, CASE.first_attempt, CASE.note)
    monkeypatch.setattr(bench, "story", lambda c: "# A story\n\nChange nothing.")
    settings = load(home=tmp_path)
    replies = iter(answers)
    send = Sender(
        settings,
        "k",
        cap=cap,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(replies))),
        tick=lambda: True,
    )
    made: list[FakeWorkspace] = []

    def checkout_for(c: Case, run_id: str) -> Path:
        path = tmp_path / "worktrees" / run_id
        subprocess.run(
            ["git", "-C", str(clone), "worktree", "add", "-q", "--detach", str(path), base],
            check=True,
        )
        return path

    def workspace_for(root: Path, name: str) -> FakeWorkspace:
        made.append(FakeWorkspace(root, start_code))
        return made[-1]

    results = tmp_path / "results"
    row = bench.replay(
        case,
        settings,
        send,
        "crew-code-think",
        checkout_for=checkout_for,
        workspace_for=workspace_for,
        results_dir=results,
    )
    return row, made, results


def test_a_blocked_session_counts_its_malformed_call(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, made, results = run(
        tmp_path,
        repo,
        [
            answer(call("view", "{not json")),
            answer(call("blocked", json.dumps({"missing": "the data", "kind": "fact"}))),
        ],
        monkeypatch=monkeypatch,
    )
    assert row["ending"] == "blocked"
    assert row["calls"] == 2
    assert row["tool_calls"] == 2
    assert row["malformed_tool_calls"] == 1
    assert row["gate_green"] is None
    assert row["prompt_tokens"] == 2000
    assert (row["concurrent_tick"], row["tick_calls"]) == (True, 2)
    assert made[0].stopped
    assert not (tmp_path / "worktrees" / row["run"]).exists()
    out = tmp_path / ".local/share/model-performance/records/benchmark" / row["case"] / row["run"]
    assert {p.name for p in out.iterdir()} >= {"start.md", "events.jsonl", "result.json"}
    assert json.loads((results / "benchmark.jsonl").read_text()) == {"suite": "benchmark", **row}
    kept = json.loads((out / "result.json").read_text())
    assert (kept["ending"], kept["session_ending"]["how"]) == ("blocked", "blocked")


def test_the_cap_ends_the_session_as_interrupted(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, made, _ = run(
        tmp_path, repo, [answer(content="Thinking.")], cap=1, monkeypatch=monkeypatch
    )
    assert (row["ending"], row["stop"], row["calls"]) == ("interrupted", "call_failed", 1)
    assert made[0].stopped


def test_a_container_that_wont_start_is_refused_and_leaves_nothing(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, made, results = run(tmp_path, repo, [], start_code=126, monkeypatch=monkeypatch)
    assert (row["ending"], row["stop"]) == ("refused", "container_start")
    assert made[0].stopped
    assert not (tmp_path / "worktrees" / row["run"]).exists()
    assert (results / "benchmark.jsonl").exists()


def test_a_checkout_that_fails_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fails(c: Case, run_id: str) -> Path:
        raise subprocess.CalledProcessError(128, ["git"])

    settings = load(home=tmp_path)
    row = bench.replay(
        CASE,
        settings,
        Sender(settings, "k", cap=0, tick=lambda: False),
        "crew-code-think",
        checkout_for=fails,
        results_dir=tmp_path / "results",
    )
    assert (row["ending"], row["stop"]) == ("refused", "checkout")


def test_main_refuses_both_cases_and_all() -> None:
    with pytest.raises(SystemExit):
        bench.main(["sprint-metrics-662", "--all"])
