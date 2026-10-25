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
from benchmark.arms import Arm, arm
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
    given: str | None = None,
    arm: Arm | None = None,
    bodies: list[dict[str, Any]] | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], list[FakeWorkspace], Path]:
    clone, base = repo
    case = Case(CASE.repo, CASE.card, base, CASE.first_attempt, CASE.note)
    monkeypatch.setattr(bench, "story", lambda c: "# A story\n\nChange nothing.")
    monkeypatch.setattr(bench, "record", lambda c: given)
    settings = load(home=tmp_path)
    replies = iter(answers)

    def reply(request: httpx.Request) -> httpx.Response:
        if bodies is not None:
            bodies.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))

    send = Sender(settings, "k", cap=cap, transport=httpx.MockTransport(reply), tick=lambda: True)
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
        arm=arm,
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


def test_a_record_crew_cant_read_is_refused_before_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clone"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    (path / ".crew").mkdir()
    (path / ".crew" / "project.yaml").write_text("version: 2\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        [*git[:3], "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    row, made, _ = run(tmp_path, (path, base), [], monkeypatch=monkeypatch)
    assert (row["ending"], row["stop"]) == ("refused", "record_unreadable")
    assert made == []
    out = tmp_path / ".local/share/model-performance/records/benchmark" / row["case"] / row["run"]
    assert "version 2" in json.loads((out / "result.json").read_text())["refused"]


def test_a_given_record_is_committed_and_left_out_of_the_work(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmark.cases import CASES, record

    given = record(CASES["sprint-metrics-662"])
    assert given is not None
    seen: list[str] = []
    real = bench.give_record

    def give(root: Path, text: str) -> str:
        since = real(root, text)
        seen.append(since)
        return since

    monkeypatch.setattr(bench, "give_record", give)
    row, made, _ = run(
        tmp_path,
        repo,
        [answer(call("blocked", json.dumps({"missing": "the data", "kind": "fact"})))],
        given=given,
        monkeypatch=monkeypatch,
    )
    assert (row["ending"], row["record_authored"]) == ("blocked", True)
    assert seen and seen[0] != repo[1]
    out = tmp_path / ".local/share/model-performance/records/benchmark" / row["case"] / row["run"]
    assert ".crew/project.yaml" not in (out / "diff.patch").read_text()
    assert "(no record)" not in (out / "start.md").read_text()


def test_every_carried_record_is_one_crew_reads(tmp_path: Path) -> None:
    from crew_org.project import read_record

    from benchmark.cases import CASES, record

    for c in CASES.values():
        given = record(c)
        assert given is not None, c.name
        (tmp_path / ".crew").mkdir(exist_ok=True)
        (tmp_path / ".crew" / "project.yaml").write_text(given)
        assert read_record(tmp_path) is not None, c.name


def thought(response: dict[str, Any], reasoning: int) -> dict[str, Any]:
    usage = {**response["usage"], "completion_tokens_details": {"reasoning_tokens": reasoning}}
    return {**response, "usage": usage}


def kept(tmp_path: Path, row: dict[str, Any]) -> dict[str, Any]:
    out = tmp_path / ".local/share/model-performance/records/benchmark" / row["case"] / row["run"]
    return json.loads((out / "result.json").read_text())


BLOCKED = call("blocked", json.dumps({"missing": "the data", "kind": "fact"}))


def test_an_arm_sends_its_fields_and_names_itself(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bodies: list[dict[str, Any]] = []
    row, _, results = run(
        tmp_path,
        repo,
        [thought(answer(BLOCKED), 0)],
        arm=arm("think-off"),
        bodies=bodies,
        monkeypatch=monkeypatch,
    )
    assert (row["ending"], row["arm"], row["max_call_reasoning_tokens"]) == (
        "blocked",
        "think-off",
        0,
    )
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert json.loads((results / "benchmark.jsonl").read_text())["arm"] == "think-off"
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    assert kept(tmp_path, row)["arm"]["body"] == off


def test_thinking_that_stays_on_refuses_the_arm(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, made, _ = run(
        tmp_path,
        repo,
        [thought(answer(call("view", json.dumps({"path": "README.md"}))), 300)],
        arm=arm("think-off"),
        monkeypatch=monkeypatch,
    )
    assert (row["ending"], row["stop"], row["calls"]) == ("refused", "arm_not_applied", 0)
    assert row["max_call_reasoning_tokens"] == 300
    assert made[0].stopped
    assert "call 1 spent 300" in kept(tmp_path, row)["refused"]


def test_a_budget_the_server_ignores_is_a_result_not_a_crash(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bodies: list[dict[str, Any]] = []
    row, _, _ = run(
        tmp_path,
        repo,
        [thought(answer(BLOCKED), 1400)],
        arm=arm("budget-128"),
        bodies=bodies,
        monkeypatch=monkeypatch,
    )
    assert (row["ending"], row["stop"]) == ("refused", "budget_unenforced")
    assert bodies[0]["custom_params"] == {"thinking_budget": 128}
    assert kept(tmp_path, row)["reasoning_by_call"] == [1400]


def test_a_budget_kept_runs_as_usual(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, _, _ = run(
        tmp_path,
        repo,
        [thought(answer(BLOCKED), 120)],
        arm=arm("budget-128"),
        monkeypatch=monkeypatch,
    )
    assert (row["ending"], row["max_call_reasoning_tokens"]) == ("blocked", 120)


def test_dropped_reasoning_leaves_the_request_not_the_session(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = answer(call("view", json.dumps({"path": "README.md"})))
    first["choices"][0]["message"]["reasoning_content"] = "Look first."
    bodies: list[dict[str, Any]] = []
    row, _, _ = run(
        tmp_path,
        repo,
        [first, answer(BLOCKED)],
        arm=arm("reasoning-dropped"),
        bodies=bodies,
        monkeypatch=monkeypatch,
    )
    assert row["ending"] == "blocked"
    sent = [m for m in bodies[1]["messages"] if m["role"] == "assistant"]
    assert sent and all("reasoning_content" not in m for m in sent)


def test_a_compaction_arm_records_its_limit_and_when_it_fired(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    view = call("view", json.dumps({"path": "README.md"}))
    row, _, _ = run(
        tmp_path,
        repo,
        [answer(view), answer(view), answer(BLOCKED)],
        arm=arm("compact-1"),
        monkeypatch=monkeypatch,
    )
    record = kept(tmp_path, row)
    assert record["compact_at"] == 1000
    # The fake's prompt is 1000 tokens a call: it compacts before call 2, and can't get under.
    assert [c["turn"] for c in record["compactions"]] == [2]
    assert (row["compactions"], row["stop"]) == (1, "context_full")


def test_a_baseline_run_says_no_arm(
    tmp_path: Path, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row, _, _ = run(tmp_path, repo, [answer(BLOCKED)], monkeypatch=monkeypatch)
    assert (row["arm"], row["max_call_reasoning_tokens"]) == (None, None)
    assert kept(tmp_path, row)["compact_at"] == 125_000


@pytest.mark.parametrize(
    "argv",
    [
        ["sprint-metrics-567", "--arm", "warp-9"],
        ["sprint-metrics-567", "--arm", "effort-medium", "--model", "crew-code"],
    ],
)
def test_main_refuses_an_unknown_arm_or_two_aliases(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        bench.main(argv)
