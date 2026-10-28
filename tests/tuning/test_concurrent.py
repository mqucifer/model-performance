"""A concurrent run: the memory ceiling, the sessions it starts, and the row it leaves.

No session, container or Grafana request is started: the sessions are fakes that write
their benchmark rows, and Grafana's numbers are given.
"""

from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any

import pytest

from common.config import load
from common.results import problems
from tuning import concurrent as conc

GIB = conc.GIB


def test_docker_sizes_are_read_in_each_unit() -> None:
    assert conc.size("1.5GiB") == 1.5 * GIB
    assert conc.size("512MiB") == 512 * 1024**2
    assert conc.size(" 0B ") == 0
    with pytest.raises(ValueError):
        conc.size("lots")


def test_free_memory_is_dockers_less_what_its_containers_use() -> None:
    answers = {
        "info": f"{int(11.67 * GIB)}\n",
        "stats": "1.1GiB / 11.67GiB\n1.5GiB / 11.67GiB\n\n",
    }
    free = conc.docker_free_gib(lambda argv: answers[argv[1]])
    assert free == pytest.approx(9.07, abs=0.01)


@pytest.mark.parametrize(("free", "most"), [(9.07, 5), (10.57, 6), (12.5, 8), (0.4, 0)])
def test_the_ceiling_leaves_a_reserve(free: float, most: int) -> None:
    assert conc.ceiling(free) == most


def test_the_cases_are_repeated_in_order_to_make_n() -> None:
    assert conc.chosen(7, ["a", "b", "c"]) == ["a", "b", "c", "a", "b", "c", "a"]
    assert len(conc.chosen(8)) == 8


def test_each_session_is_capped_and_tagged() -> None:
    argv = conc.session_argv("sprint-metrics-662", 6, "record", "B1", 150)
    assert argv[1:7] == ["-m", "tuning.session", "--memory", "1536m", "--", "sprint-metrics-662"]
    assert argv[7:] == ["--sessions", "6", "--serving", "record", "--batch", "B1", "--cap", "150"]


def test_the_model_reaches_each_session_only_when_given() -> None:
    argv = conc.session_argv("sprint-metrics-662", 6, "record", "B1", None, "crew-candidate")
    assert argv[7:] == [
        "--sessions", "6", "--serving", "record", "--batch", "B1", "--model", "crew-candidate"
    ]  # fmt: skip
    assert "--model" not in conc.session_argv("sprint-metrics-662", 6, "record", "B1", 150)


class Fake:
    """A session that has already ended, leaving its row."""

    returncode = 0

    def __init__(self, argv: list[str], results: Path, ending: str, green: bool | None) -> None:
        self.argv = argv
        batch = argv[argv.index("--batch") + 1]
        row = {
            "suite": "benchmark",
            "case": argv[6],
            "run": f"r{argv[6]}",
            "batch": batch,
            "sessions": int(argv[argv.index("--sessions") + 1]),
            "ending": ending,
            "gate_green": green,
            "wall_s": 600.0 if green else 900.0,
            "calls": 30,
            "prompt_tokens": 1000,
            "completion_tokens": 6000,
            "model_s": 300.0 if green else 600.0,
            "crew_commit": "abc",
            "model_alias": argv[argv.index("--model") + 1]
            if "--model" in argv
            else "crew-code-think",
            "concurrent_tick": False,
            "tick_calls": 0,
        }
        with (results / "benchmark.jsonl").open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    def wait(self) -> int:
        return 0


SPARK = {
    "ttft_p50_s": 1.2,
    "ttft_p95_s": 9.5,
    "queue_max": 0.0,
    "running_max": 6.0,
    "cache_hit_mean": 0.81,
    "kv_use_max": 0.4,
    "spec_accept_mean": 3.1,
    "gen_throughput_mean": 140.0,
    "grafana": True,
}


def test_a_run_leaves_one_row_of_its_sessions_and_the_spark(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    started: list[list[str]] = []

    def start(argvs: list[list[str]], out: Path) -> list[Any]:
        started.extend(argvs)
        return [Fake(a, results, "done", i != 1) for i, a in enumerate(argvs)]

    row = conc.concurrent(
        load(home=tmp_path),
        6,
        "record",
        150,
        None,
        10.6,
        read_grafana=lambda out, a, b: SPARK,
        others=lambda a, b, own: None,
        results_dir=results,
        start=start,
    )
    assert len(started) == 6
    assert (row["stories"], row["done"], row["gate_green"]) == (6, 6, 5)
    assert row["story_wall_s_mean"] == 650.0
    assert row["story_wall_s_max"] == 900.0
    assert row["session_tps_mean"] == 18.3  # five at 20 tokens/s, one at 10
    assert row["calls"] == 180
    assert row["running_max"] == 6.0
    assert row["other_calls"] is None
    written = json.loads((results / "tuning.jsonl").read_text())
    assert problems(written) == []
    assert written["workspace_memory"] == "1536m"
    plan = (
        tmp_path
        / ".local/share/model-performance/records/tuning/concurrent"
        / row["run"]
        / "plan.json"
    )
    assert json.loads(plan.read_text())["sessions"] == 6


def run_with(tmp_path: Path, model: str | None) -> tuple[dict[str, Any], list[list[str]]]:
    results = tmp_path / "results"
    results.mkdir()
    started: list[list[str]] = []

    def start(argvs: list[list[str]], out: Path) -> list[Any]:
        started.extend(argvs)
        return [Fake(a, results, "done", True) for a in argvs]

    row = conc.concurrent(
        load(home=tmp_path),
        4,
        "tensorfold-1.1.6-mlx4",
        None,
        None,
        10.6,
        read_grafana=lambda out, a, b: SPARK,
        others=lambda a, b, own: None,
        results_dir=results,
        start=start,
        model=model,
    )
    return row, started


def test_every_session_calls_the_model_and_the_row_names_it(tmp_path: Path) -> None:
    row, started = run_with(tmp_path, "crew-candidate")
    assert len(started) == 4
    assert all(a[a.index("--model") + 1] == "crew-candidate" for a in started)
    assert row["model_alias"] == "crew-candidate"
    assert row["serving"] == "tensorfold-1.1.6-mlx4"
    assert json.loads((tmp_path / "results/tuning.jsonl").read_text())["model_alias"] == (
        "crew-candidate"
    )


def test_without_a_model_the_sessions_call_the_developers_alias(tmp_path: Path) -> None:
    row, started = run_with(tmp_path, None)
    assert not any("--model" in a for a in started)
    assert row["model_alias"] == "crew-code-think"


def test_the_row_names_the_model_when_no_session_left_a_row() -> None:
    assert conc.summary([], 4, "crew-candidate")["model_alias"] == "crew-candidate"
    assert conc.summary([], 4)["model_alias"] is None


def test_main_passes_the_model_on(monkeypatch: pytest.MonkeyPatch) -> None:
    import swap.runners

    monkeypatch.setattr(swap.runners, "ticks_running", lambda: False)
    monkeypatch.setattr(conc, "docker_free_gib", lambda: 10.6)
    monkeypatch.setattr(conc.signal, "signal", lambda *a: None)
    monkeypatch.setattr(conc, "load", lambda: None)
    seen: dict[str, Any] = {}

    def fake(*a: Any, **k: Any) -> dict[str, Any]:
        seen.update(k)
        raise SystemExit(0)

    monkeypatch.setattr(conc, "concurrent", fake)
    with pytest.raises(SystemExit):
        conc.main(["4", "--model", "crew-candidate", "--serving", "tensorfold-1.1.6-mlx4"])
    assert seen["model"] == "crew-candidate"


def test_another_runs_rows_arent_counted(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    Fake(conc.session_argv("x", 4, "record", "OTHER", None), results, "done", True)
    row = conc.concurrent(
        load(home=tmp_path),
        1,
        "record",
        None,
        ["sprint-metrics-662"],
        10.6,
        read_grafana=lambda out, a, b: SPARK,
        others=lambda a, b, own: None,
        results_dir=results,
        start=lambda argvs, out: [Fake(a, results, "blocked", None) for a in argvs],
    )
    assert (row["stories"], row["done"], row["gate_green"]) == (1, 0, 0)


def test_an_interrupt_stops_every_session_and_still_leaves_a_row(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()

    class Running:
        returncode = None

        def __init__(self) -> None:
            self.signals: list[int] = []

        def wait(self, timeout: float | None = None) -> int:
            if not self.signals:
                raise KeyboardInterrupt
            return 130

        def poll(self) -> None:
            return None

        def send_signal(self, signum: int) -> None:
            self.signals.append(signum)

    children = [Running(), Running()]
    row = conc.concurrent(
        load(home=tmp_path),
        2,
        "record",
        None,
        None,
        10.6,
        read_grafana=lambda out, a, b: SPARK,
        others=lambda a, b, own: None,
        results_dir=results,
        start=lambda argvs, out: children,
    )
    assert row["ending"] == "interrupted"
    assert all(c.signals == [signal.SIGINT] for c in children)
    assert json.loads((results / "tuning.jsonl").read_text())["ending"] == "interrupted"


def test_main_refuses_more_sessions_than_fit(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import swap.runners

    monkeypatch.setattr(swap.runners, "ticks_running", lambda: False)
    monkeypatch.setattr(conc, "docker_free_gib", lambda: 9.07)
    monkeypatch.setattr(conc, "concurrent", lambda *a, **k: pytest.fail("started"))
    assert conc.main(["6"]) == 2
    assert "the ceiling is 5" in capsys.readouterr().err


def test_main_refuses_while_a_tick_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    import swap.runners

    monkeypatch.setattr(swap.runners, "ticks_running", lambda: True)
    monkeypatch.setattr(conc, "docker_free_gib", lambda: pytest.fail("read"))
    assert conc.main(["4"]) == 2


def test_other_calls_leave_out_every_session_of_the_run(tmp_path: Path) -> None:
    from collections import Counter

    results = tmp_path / "results"
    results.mkdir()
    settings = load(home=tmp_path)
    seen: list[set[str]] = []

    def start(argvs: list[list[str]], out: Path) -> list[Any]:
        made = [Fake(a, results, "done", True) for a in argvs]
        for i, a in enumerate(argvs):
            events = settings.records_dir / "benchmark" / a[6] / f"r{a[6]}" / "events.jsonl"
            events.parent.mkdir(parents=True, exist_ok=True)
            line = {"kind": "llm.finished", "detail": {"response_id": f"own-{i}"}}
            events.write_text(json.dumps(line) + "\n")
        return made

    def others(since, until, own):
        seen.append(set(own))
        return Counter({"claude-builders/crew-local": 3})

    row = conc.concurrent(
        settings,
        2,
        "record",
        None,
        None,
        10.6,
        read_grafana=lambda out, a, b: SPARK,
        results_dir=results,
        start=start,
        others=others,
    )
    assert seen == [{"own-0", "own-1"}]
    assert (row["other_calls"], row["other_aliases"]) == (3, "claude-builders")
