"""The tuned launch differs from infra's in one flag, and every ending brings the 27B back.

fixtures/infra/compose/spark/sglang/ holds infra's compose.yaml and check_launch.py,
byte for byte, at
mqucifer/infra cbb7abc (mqucifer/infra#42), so the proof runs in CI without infra.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from swap import core
from tests.swap.conftest import FakeRunner
from tuning import launch

FIXTURES = Path(__file__).parent / "fixtures"
INFRA = FIXTURES / "infra"
SGLANG = INFRA / "compose" / "spark" / "sglang"
RECORD = (SGLANG / "compose.yaml").read_text()
COMMAND = ["uv", "run", "concurrent", "6"]


def checker_flags():
    spec = importlib.util.spec_from_file_location("infra_check_launch", SGLANG / "check_launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.flags


def compose_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


@pytest.fixture
def config():
    from swap.config import load

    return replace(load(), infra_dir=INFRA)


# What a setting is.


def test_a_setting_is_named_without_its_dashes_or_with_them() -> None:
    assert launch.parse("mem-fraction-static=0.88")[1] == "0.88"
    assert launch.parse("--max-running-requests=12")[0].flag == "--max-running-requests"
    assert launch.parse("enable-mixed-chunk") == (launch.SETTINGS["--enable-mixed-chunk"], None)


@pytest.mark.parametrize(
    "spec",
    [
        "model-path=Org/Other",
        "port=9999",
        "mem-fraction-static=lots",
        "max-running-requests=",
        "enable-mixed-chunk=1",
        "schedule-policy=lpm --port 1",
    ],
)
def test_anything_outside_the_issues_settings_is_refused(spec: str) -> None:
    with pytest.raises(launch.Refused):
        launch.parse(spec)


def test_the_serving_name_is_a_short_name() -> None:
    from common.results import NAME

    for spec in ("mem-fraction-static=0.88", "enable-mixed-chunk", "schedule-policy=lpm"):
        assert NAME.fullmatch(launch.serving_name(*launch.parse(spec)))


# The launch.


def test_a_recorded_flag_has_its_one_line_changed() -> None:
    text = launch.tuned(RECORD, *launch.parse("mem-fraction-static=0.88"))
    assert "--mem-fraction-static 0.88\n" in text
    assert "0.80" not in text.split("command:")[1]
    assert len(text.splitlines()) == len(RECORD.splitlines())


def test_a_speculative_flag_is_changed_inside_the_27Bs_draft() -> None:
    text = launch.tuned(RECORD, *launch.parse("speculative-num-draft-tokens=4"))
    assert "--speculative-num-draft-tokens 4\n" in text
    assert "${SPECULATIVE_ARGS---speculative-algorithm DFLASH" in text


def test_a_flag_the_record_doesnt_set_is_added_after_the_port() -> None:
    text = launch.tuned(RECORD, *launch.parse("schedule-policy=lpm"))
    assert "--port 8888\n      --schedule-policy lpm\n" in text
    assert len(text.splitlines()) == len(RECORD.splitlines()) + 1


@pytest.mark.skipif(not compose_available(), reason="docker compose isn't installed")
@pytest.mark.parametrize(
    "spec",
    [
        "mem-fraction-static=0.88",
        "max-mamba-cache-size=240",
        "chunked-prefill-size=4096",
        "speculative-num-draft-tokens=4",
        "schedule-policy=lpm",
        "enable-mixed-chunk",
        "max-running-requests=12",
    ],
)
def test_each_setting_is_proved_to_change_its_flag_alone(spec: str) -> None:
    setting, value = launch.parse(spec)
    launch.prove(RECORD, launch.tuned(RECORD, setting, value), setting, checker_flags())


@pytest.mark.skipif(not compose_available(), reason="docker compose isn't installed")
def test_a_second_change_is_caught() -> None:
    setting, value = launch.parse("mem-fraction-static=0.88")
    text = launch.tuned(RECORD, setting, value).replace("shm_size: 32gb", "shm_size: 16gb")
    with pytest.raises(launch.Refused, match="service.shm_size"):
        launch.prove(RECORD, text, setting, checker_flags())
    text = launch.tuned(RECORD, setting, value).replace(
        "--max-running-requests 8", "--max-running-requests 9"
    )
    with pytest.raises(launch.Refused, match="--max-running-requests"):
        launch.prove(RECORD, text, setting, checker_flags())


def test_differences_compare_flags_by_value() -> None:
    def svc(command: list[str], name: str = "a") -> dict:
        return {"services": {"sglang": {"command": command, "container_name": name, "image": "i"}}}

    head = ["python3", "-m", "sglang.launch_server"]
    flags = checker_flags()
    assert launch.differences(svc([*head, "--x", "1"]), svc([*head, "--x", "1"], "b"), flags) == []
    assert launch.differences(svc([*head, "--x", "1"]), svc([*head, "--x", "2"]), flags) == ["--x"]
    assert launch.differences(svc(head), svc([*head, "--y"]), flags) == ["--y"]


# Every ending, against the swap's fake runner.

TUNED = launch.tuned(RECORD, *launch.parse("mem-fraction-static=0.88"))
PREFLIGHT = [
    "ticks?",
    "ssh true",
    "running? qwen3.8-27b-sglang",
    "ssh ! docker container inspect spark-tuning >/dev/null 2>&1",
    "answers? crew-local",
    "ssh env CONTAINER_NAME=spark-tuning docker compose -p spark-tuning -f - config -q"
    " <spark-sglang",
]
STARTED = [
    "ssh docker stop qwen3.8-27b-sglang",
    "ssh env CONTAINER_NAME=spark-tuning docker compose -p spark-tuning -f - up -d <spark-sglang",
    "answers? crew-local",
]
RESTORE = [
    "ssh { docker compose -p spark-tuning down --timeout 60 || docker rm -f spark-tuning; }"
    " && ! docker container inspect spark-tuning >/dev/null 2>&1",
    "ssh docker start qwen3.8-27b-sglang",
    "answers? crew-local",
]


def tune(runner: FakeRunner, config) -> int:
    return launch.tune(runner, config, "mem-fraction-static:0.88", COMMAND, TUNED)


def test_a_run_tunes_runs_and_restores(config) -> None:
    runner = FakeRunner()
    assert tune(runner, config) == 0
    assert runner.steps == [*PREFLIGHT, *STARTED, f"run {' '.join(COMMAND)}", *RESTORE]
    assert runner.command_env == {"TUNE_SERVING": "mem-fraction-static:0.88"}


def test_a_tick_refuses_before_anything_is_touched(config) -> None:
    runner = FakeRunner(ticks=True)
    assert tune(runner, config) == core.REFUSED
    assert runner.steps == ["ticks?"]


def test_a_27B_that_isnt_running_is_refused(config) -> None:
    runner = FakeRunner(exited={"qwen3.8-27b-sglang"})
    assert tune(runner, config) == core.REFUSED
    assert not any("docker stop" in s for s in runner.steps)


def test_only_docker_start_brings_the_27B_back(config) -> None:
    runner = FakeRunner()
    assert tune(runner, replace(config, restore="compose")) == core.REFUSED
    assert runner.steps == []


def exits_before_answering() -> FakeRunner:
    runner = FakeRunner(exited={"spark-tuning"})

    def started(command: str) -> None:
        if command.endswith("up -d"):
            runner.answers_after["crew-local"] = 1

    runner.on_remote = started
    return runner


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(remote_fails={"up -d"}),
        FakeRunner(remote_fails={"docker stop"}),
        exits_before_answering(),
    ],
    ids=["didnt-start", "didnt-stop", "exited-before-answering"],
)
def test_a_launch_that_fails_still_restores(runner: FakeRunner, config) -> None:
    assert tune(runner, config) == core.CANDIDATE_FAILED
    assert not any(s.startswith("run ") for s in runner.steps)
    assert runner.steps[-3:] == RESTORE


def test_an_interrupted_command_still_restores(config) -> None:
    runner = FakeRunner(command_result=KeyboardInterrupt())
    assert tune(runner, config) == core.INTERRUPTED
    assert runner.steps[-3:] == RESTORE


def test_a_failed_command_keeps_its_code_and_restores(config) -> None:
    runner = FakeRunner(command_result=1)
    assert tune(runner, config) == 1
    assert runner.steps[-3:] == RESTORE


def test_a_27B_that_doesnt_come_back_says_so(config) -> None:
    runner = FakeRunner(remote_fails={"docker start"})

    def after_run(command: str) -> None:
        if "docker start" in command:
            runner.never_answers.add("crew-local")

    runner.on_remote = after_run
    assert tune(runner, config) == core.RESTORE_FAILED
    assert any("THE 27B DID NOT COME BACK" in m for m in runner.messages)


def test_the_dry_run_prints_every_step_and_changes_nothing(capsys, monkeypatch) -> None:
    if not compose_available():
        pytest.skip("docker compose isn't installed")
    import swap.runners

    monkeypatch.setattr(swap.runners, "ticks_running", lambda: False)
    code = launch.main(
        ["--set", "mem-fraction-static=0.88", "--dry-run", "--infra-dir", str(INFRA), "--", "true"]
    )
    err = capsys.readouterr().err
    assert code == 0, err
    assert "differs from infra's record in --mem-fraction-static only" in err
    assert err.count("[dry-run] ssh") == 8
    assert "docker start qwen3.8-27b-sglang" in err
