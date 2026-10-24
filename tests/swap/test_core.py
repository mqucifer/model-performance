"""The swap's endings, against a fake runner: each one restores the 27B, or says it didn't."""

from __future__ import annotations

import os
import signal
from dataclasses import replace

import pytest

from swap import core
from swap.config import Config, ConfigError, check

from .conftest import FakeRunner

MODEL = "Qwen/Qwen3.8-8B"
COMMAND = ["uv", "run", "bench", "--case", "one"]

PREFLIGHT = ["ticks?", "ssh true", "answers? crew-local", "lists? crew-candidate"]
SWAP = [
    "ssh docker stop qwen3.8-27b-sglang",
    "ssh env MODEL_PATH=Qwen/Qwen3.8-8B SERVED_MODEL_NAME=crew-candidate-sglang "
    "SPECULATIVE_ARGS='' CONTAINER_NAME=sglang-candidate "
    "docker compose -p sglang-candidate -f - up -d <stdin",
    "answers? crew-candidate",
]
RESTORE = [
    "ssh docker compose -p sglang-candidate down --timeout 60 || docker rm -f sglang-candidate",
    "ssh cd ~/Qwen3.8-27B-SGLang-DGX-Spark && ./start-dflash.sh",
    "answers? crew-local",
]


def test_success_swaps_runs_and_restores(config: Config, compose_text: str) -> None:
    runner = FakeRunner()
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == 0
    assert runner.steps == PREFLIGHT + SWAP + ["run uv run bench --case one"] + RESTORE


def test_failed_command_still_restores_and_passes_its_code_on(
    config: Config, compose_text: str
) -> None:
    runner = FakeRunner(command_result=7)
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == 7
    assert runner.steps[-3:] == RESTORE


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), core.Interrupted("SIGTERM")])
def test_interrupt_during_the_command_restores(
    config: Config, compose_text: str, interrupt: BaseException
) -> None:
    runner = FakeRunner(command_result=interrupt)
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == core.INTERRUPTED
    assert runner.steps[-3:] == RESTORE


def test_sigterm_to_the_swap_restores(config: Config, compose_text: str) -> None:
    def terminate(command: str) -> None:
        if "up -d" in command and "MODEL_PATH" in command:
            os.kill(os.getpid(), signal.SIGTERM)

    runner = FakeRunner(on_remote=terminate)
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == core.INTERRUPTED
    assert not any(step.startswith("run ") for step in runner.steps)
    assert runner.steps[-3:] == RESTORE


def test_ctrl_c_during_the_restore_is_ignored(config: Config, compose_text: str) -> None:
    def interrupt(command: str) -> None:
        if "start-dflash" in command:
            os.kill(os.getpid(), signal.SIGINT)

    runner = FakeRunner(on_remote=interrupt)
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == 0
    assert runner.steps[-3:] == RESTORE
    assert any("SIGINT ignored" in m for m in runner.messages)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_candidate_that_never_answers_skips_the_command_and_restores(
    config: Config, compose_text: str
) -> None:
    runner = FakeRunner(never_answers={"crew-candidate"})
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == core.CANDIDATE_FAILED
    assert not any(step.startswith("run ") for step in runner.steps)
    polls = runner.steps.count("answers? crew-candidate")
    assert polls == int(config.ready_timeout_s // config.poll_s) + 1
    assert runner.steps[-3:] == RESTORE


def test_candidate_answering_after_a_few_polls_runs_the_command(
    config: Config, compose_text: str
) -> None:
    runner = FakeRunner(answers_after={"crew-candidate": 3})
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == 0
    assert runner.steps.count("answers? crew-candidate") == 4
    assert "run uv run bench --case one" in runner.steps


@pytest.mark.parametrize("failing", ["docker stop", "MODEL_PATH"])
def test_failed_stop_or_start_restores(config: Config, compose_text: str, failing: str) -> None:
    runner = FakeRunner(remote_fails={failing})
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == core.CANDIDATE_FAILED
    assert not any(step.startswith("run ") for step in runner.steps)
    assert runner.steps[-3:] == RESTORE


def test_restore_that_never_answers_says_so_and_gives_the_manual_steps(
    config: Config, compose_text: str
) -> None:
    class BaselineNeverComesBack(FakeRunner):
        def remote(self, command: str, stdin: bytes | None = None) -> int:
            if "docker stop" in command:
                self.never_answers.add("crew-local")
            return super().remote(command, stdin)

    runner = BaselineNeverComesBack()
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == core.RESTORE_FAILED
    assert any("THE 27B DID NOT COME BACK" in m and "start-dflash.sh" in m for m in runner.messages)


def test_failed_candidate_removal_still_restores(config: Config, compose_text: str) -> None:
    runner = FakeRunner(remote_fails={"down --timeout"})
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == 0
    assert runner.steps[-3:] == RESTORE


@pytest.mark.parametrize(
    ("runner", "reason"),
    [
        (FakeRunner(ticks=True), "tick is running"),
        (FakeRunner(remote_fails={"true"}), "doesn't answer ssh"),
        (FakeRunner(never_answers={"crew-local"}), "nothing to restore to"),
        (FakeRunner(listed=False), "no crew-candidate alias"),
    ],
)
def test_preflight_refuses_and_touches_nothing(
    config: Config, compose_text: str, runner: FakeRunner, reason: str
) -> None:
    assert core.swap(runner, config, MODEL, COMMAND, compose_text) == core.REFUSED
    assert any(reason in m for m in runner.messages)
    assert not any("docker" in step for step in runner.steps)


def test_a_tick_is_checked_before_anything_else(config: Config, compose_text: str) -> None:
    runner = FakeRunner(ticks=True)
    core.swap(runner, config, MODEL, COMMAND, compose_text)
    assert runner.steps == ["ticks?"]


def test_launch_without_the_variables_is_refused(config: Config) -> None:
    runner = FakeRunner()
    launch = "services:\n  sglang:\n    command: --model-path ${MODEL_PATH}\n"
    assert core.swap(runner, config, MODEL, COMMAND, launch) == core.REFUSED
    assert any("SERVED_MODEL_NAME, SPECULATIVE_ARGS, CONTAINER_NAME" in m for m in runner.messages)
    assert runner.steps == ["ticks?"]


@pytest.mark.parametrize(
    ("mode", "command", "fed"),
    [
        ("container", "ssh docker start qwen3.8-27b-sglang", False),
        ("compose", "ssh docker compose -f - up -d <stdin", True),
    ],
)
def test_restore_modes(
    config: Config, compose_text: str, mode: str, command: str, fed: bool
) -> None:
    runner = FakeRunner()
    assert core.swap(runner, replace(config, restore=mode), MODEL, COMMAND, compose_text) == 0
    assert runner.steps[-2] == command


def test_model_is_quoted_for_the_remote_shell(config: Config) -> None:
    command = core.start_candidate(config, "org/model;rm -rf ~")
    assert "MODEL_PATH='org/model;rm -rf ~'" in command


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8888",  # SGLang's port
        "http://spark:4000",  # any host but the Mac
        "http://localhost:4001",
    ],
)
def test_checks_never_reach_around_the_proxy(config: Config, url: str) -> None:
    with pytest.raises(ConfigError, match="through the proxy"):
        check(replace(config, base_url=url))


def test_no_step_names_sglangs_port(config: Config, compose_text: str) -> None:
    runner = FakeRunner(command_result=1)
    core.swap(runner, config, MODEL, COMMAND, compose_text)
    assert not any("8888" in step for step in runner.steps)


def test_candidate_cannot_take_the_27bs_container(config: Config) -> None:
    with pytest.raises(ConfigError):
        check(replace(config, candidate_container=config.baseline_container))
