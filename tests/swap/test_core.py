"""The swap's endings, against a fake runner: each one restores the 27B, or says it didn't."""

from __future__ import annotations

import os
import signal
from dataclasses import replace

import pytest

from swap import core
from swap.config import Config, ConfigError, check

from .conftest import FakeRunner, launch

MODEL = "Qwen/Qwen3.8-8B"
COMMAND = ["uv", "run", "bench", "--case", "one"]

PREFLIGHT = ["ticks?", "ssh true", "answers? crew-local", "lists? crew-candidate"]
SWAP = [
    "ssh docker stop qwen3.8-27b-sglang",
    "ssh env MODEL_PATH=Qwen/Qwen3.8-8B SERVED_MODEL_NAME=crew-candidate "
    "SPECULATIVE_ARGS='' CONTAINER_NAME=spark-candidate "
    "docker compose -p spark-candidate -f - up -d <sglang",
    "answers? crew-candidate",
]
RESTORE = [
    "ssh docker compose -p spark-candidate down --timeout 60 || docker rm -f spark-candidate",
    "ssh cd ~/Qwen3.8-27B-SGLang-DGX-Spark && ./start-dflash.sh",
    "answers? crew-local",
]


def swap(runner: FakeRunner, config: Config, engine: str = "sglang", model: str = MODEL) -> int:
    chosen = config.engine(engine)
    return core.swap(
        runner,
        config,
        chosen,
        model,
        COMMAND,
        launch(config, chosen),
        launch(config, config.baseline),
    )


def test_success_swaps_runs_and_restores(config: Config) -> None:
    runner = FakeRunner()
    assert swap(runner, config) == 0
    assert runner.steps == PREFLIGHT + SWAP + ["run uv run bench --case one"] + RESTORE
    assert runner.command_env == {
        "SWAP_MODEL": MODEL,
        "SWAP_ENGINE": "sglang",
        "SWAP_ALIAS": "crew-candidate",
        "SWAP_SEED_REQUIRED": "0",
    }


def test_tensorfold_arm_starts_its_own_launch_seeds_its_checks_and_restores_sglang(
    config: Config,
) -> None:
    runner = FakeRunner()
    assert swap(runner, config, engine="tensorfold", model="nvidia/Nemotron-3.5-Bolt") == 0
    assert (
        runner.steps
        == PREFLIGHT
        + [
            "ssh docker stop qwen3.8-27b-sglang",
            # Only the variables TensorFold's launch takes: no speculative draft to empty.
            "ssh env MODEL_PATH=nvidia/Nemotron-3.5-Bolt SERVED_MODEL_NAME=crew-candidate "
            "CONTAINER_NAME=spark-candidate "
            "docker compose -p spark-candidate -f - up -d <tensorfold",
            "answers? crew-candidate seeded",
            "run uv run bench --case one",
        ]
        + RESTORE
    )
    assert runner.command_env["SWAP_ENGINE"] == "tensorfold"
    assert runner.command_env["SWAP_SEED_REQUIRED"] == "1"


def test_tensorfold_arm_restores_with_sglangs_record(config: Config) -> None:
    runner = FakeRunner()
    config = replace(config, restore="compose")
    assert swap(runner, config, engine="tensorfold") == 0
    assert runner.steps[-2] == "ssh docker compose -f - up -d <sglang"


def test_tensorfold_candidate_that_exits_fails_at_once(config: Config) -> None:
    runner = FakeRunner(never_answers={"crew-candidate"}, exited={"spark-candidate"})
    assert swap(runner, config, engine="tensorfold") == core.CANDIDATE_FAILED
    assert runner.steps.count("answers? crew-candidate seeded") == 1
    assert "running? spark-candidate" in runner.steps
    assert any("spark-candidate isn't running" in m for m in runner.messages)
    assert runner.steps[-3:] == RESTORE


def test_failed_command_still_restores_and_passes_its_code_on(config: Config) -> None:
    runner = FakeRunner(command_result=7)
    assert swap(runner, config) == 7
    assert runner.steps[-3:] == RESTORE


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), core.Interrupted("SIGTERM")])
def test_interrupt_during_the_command_restores(config: Config, interrupt: BaseException) -> None:
    runner = FakeRunner(command_result=interrupt)
    assert swap(runner, config) == core.INTERRUPTED
    assert runner.steps[-3:] == RESTORE


def test_sigterm_to_the_swap_restores(config: Config) -> None:
    def terminate(command: str) -> None:
        if "up -d" in command and "MODEL_PATH" in command:
            os.kill(os.getpid(), signal.SIGTERM)

    runner = FakeRunner(on_remote=terminate)
    assert swap(runner, config) == core.INTERRUPTED
    assert not any(step.startswith("run ") for step in runner.steps)
    assert runner.steps[-3:] == RESTORE


def test_ctrl_c_during_the_restore_is_ignored(config: Config) -> None:
    def interrupt(command: str) -> None:
        if "start-dflash" in command:
            os.kill(os.getpid(), signal.SIGINT)

    runner = FakeRunner(on_remote=interrupt)
    assert swap(runner, config) == 0
    assert runner.steps[-3:] == RESTORE
    assert any("SIGINT ignored" in m for m in runner.messages)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_candidate_that_never_answers_skips_the_command_and_restores(config: Config) -> None:
    runner = FakeRunner(never_answers={"crew-candidate"})
    assert swap(runner, config) == core.CANDIDATE_FAILED
    assert not any(step.startswith("run ") for step in runner.steps)
    polls = runner.steps.count("answers? crew-candidate")
    assert polls == int(config.ready_timeout_s // config.poll_s) + 1
    assert runner.steps.count("running? spark-candidate") == polls
    assert runner.steps[-3:] == RESTORE


def test_candidate_answering_after_a_few_polls_runs_the_command(config: Config) -> None:
    runner = FakeRunner(answers_after={"crew-candidate": 3})
    assert swap(runner, config) == 0
    assert runner.steps.count("answers? crew-candidate") == 4
    assert "run uv run bench --case one" in runner.steps


@pytest.mark.parametrize("failing", ["docker stop", "MODEL_PATH"])
def test_failed_stop_or_start_restores(config: Config, failing: str) -> None:
    runner = FakeRunner(remote_fails={failing})
    assert swap(runner, config) == core.CANDIDATE_FAILED
    assert not any(step.startswith("run ") for step in runner.steps)
    assert runner.steps[-3:] == RESTORE


def test_restore_that_never_answers_says_so_and_gives_the_manual_steps(config: Config) -> None:
    class BaselineNeverComesBack(FakeRunner):
        def remote(self, command: str, stdin: bytes | None = None) -> int:
            if "docker stop" in command:
                self.never_answers.add("crew-local")
            return super().remote(command, stdin)

    runner = BaselineNeverComesBack()
    assert swap(runner, config) == core.RESTORE_FAILED
    assert any("THE 27B DID NOT COME BACK" in m and "start-dflash.sh" in m for m in runner.messages)


def test_restore_stops_waiting_when_the_27b_exits(config: Config) -> None:
    class Down(FakeRunner):
        def remote(self, command: str, stdin: bytes | None = None) -> int:
            if "docker stop" in command:
                self.never_answers.add("crew-local")
            return super().remote(command, stdin)

    runner = Down(exited={"qwen3.8-27b-sglang"})
    assert swap(runner, config) == core.RESTORE_FAILED
    assert runner.steps.count("answers? crew-local") == 2  # the preflight's, and one poll
    assert runner.steps[-1] == "running? qwen3.8-27b-sglang"


def test_failed_candidate_removal_still_restores(config: Config) -> None:
    runner = FakeRunner(remote_fails={"down --timeout"})
    assert swap(runner, config) == 0
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
    config: Config, runner: FakeRunner, reason: str
) -> None:
    assert swap(runner, config) == core.REFUSED
    assert any(reason in m for m in runner.messages)
    assert not any("docker" in step for step in runner.steps)


def test_a_tick_is_checked_before_anything_else(config: Config) -> None:
    runner = FakeRunner(ticks=True)
    swap(runner, config)
    assert runner.steps == ["ticks?"]


def test_launch_without_the_variables_is_refused(config: Config) -> None:
    runner = FakeRunner()
    bare = "name: sglang\nservices:\n  sglang:\n    command: --model-path ${MODEL_PATH}\n"
    sglang = config.engine("sglang")
    assert core.swap(runner, config, sglang, MODEL, COMMAND, bare, bare) == core.REFUSED
    assert any(
        "sglang launch doesn't take SERVED_MODEL_NAME, SPECULATIVE_ARGS, CONTAINER_NAME" in m
        for m in runner.messages
    )
    assert runner.steps == ["ticks?"]


def test_tensorfold_launch_needs_no_speculative_variable(config: Config) -> None:
    assert (
        core.check_launch(launch(config, config.engine("tensorfold")), config.engine("tensorfold"))
        == []
    )


@pytest.mark.parametrize(
    ("mode", "command"),
    [
        ("container", "ssh docker start qwen3.8-27b-sglang"),
        ("compose", "ssh docker compose -f - up -d <sglang"),
    ],
)
def test_restore_modes(config: Config, mode: str, command: str) -> None:
    runner = FakeRunner()
    assert swap(runner, replace(config, restore=mode)) == 0
    assert runner.steps[-2] == command


def test_model_is_quoted_for_the_remote_shell(config: Config) -> None:
    command = core.start_candidate(config, config.engine("sglang"), "org/model;rm -rf ~")
    assert "MODEL_PATH='org/model;rm -rf ~'" in command


def test_liveness_reads_dockers_state_not_the_engine(config: Config) -> None:
    command = core.still_running("spark-candidate")
    assert "docker inspect" in command and "8888" not in command and "curl" not in command


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8888",  # the engine's port
        "http://spark:4000",  # any host but the Mac
        "http://localhost:4001",
    ],
)
def test_checks_never_reach_around_the_proxy(config: Config, url: str) -> None:
    with pytest.raises(ConfigError, match="through the proxy"):
        check(replace(config, base_url=url))


@pytest.mark.parametrize("engine", ["sglang", "tensorfold"])
def test_no_step_names_the_engines_port(config: Config, engine: str) -> None:
    runner = FakeRunner(command_result=1, answers_after={"crew-candidate": 2})
    swap(runner, config, engine=engine)
    assert not any("8888" in step for step in runner.steps)


def test_unknown_engine_is_refused(config: Config) -> None:
    with pytest.raises(ConfigError, match="no engine 'vllm'"):
        config.engine("vllm")


def test_engine_without_the_required_variables_is_refused(config: Config) -> None:
    broken = replace(config.engine("tensorfold"), variables=("MODEL_PATH",))
    with pytest.raises(ConfigError, match="tensorfold"):
        check(replace(config, engines={**config.engines, "tensorfold": broken}))


def test_candidate_cannot_take_the_27bs_container(config: Config) -> None:
    with pytest.raises(ConfigError):
        check(replace(config, candidate_container=config.baseline_container))
