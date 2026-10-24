"""One swap: the Spark serves a candidate model for one command, then the 27B again.

The steps, in order (mqucifer/model-performance#2, ADR 0004 in mqucifer/project-print):

  preflight   refuse while a tick runs; the Spark answers ssh; the 27B answers
              through LiteLLM; LiteLLM knows the candidate's alias
  swap        stop the 27B; start the candidate from its engine's launch,
              recorded in infra, with only the model changed; wait until it
              answers through LiteLLM
  run         the given command
  restore     always, once the 27B was touched: remove the candidate, bring the
              27B back on its own engine, and wait until it answers through
              LiteLLM again

The candidate's engine is SGLang, as the 27B's, or one that replaces it on the
same port, such as TensorFold (mqucifer/model-performance#4).

Every check is a request to LiteLLM on the Mac's :4000, with a seed when the
engine needs one. Nothing here knows the engine's port. While a wait goes on,
the container's own state is read over ssh (`docker inspect`), so a candidate
that exits fails at once rather than at the timeout. A runner carries the steps
out: the real one over ssh and HTTP, the dry one by printing them, and the
tests' fake by recording them.
"""

from __future__ import annotations

import shlex
import signal
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Protocol

from swap.config import Config, Engine

# Exit codes of the swap's own endings. Otherwise it exits with the command's.
REFUSED = 2
RESTORE_FAILED = 3
CANDIDATE_FAILED = 4
INTERRUPTED = 130

SHIELDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Interrupted(Exception):
    """SIGTERM or SIGHUP arrived; handled like Ctrl-C."""


class Runner(Protocol):
    def say(self, message: str) -> None: ...
    def ticks_running(self) -> bool: ...
    def remote(self, command: str, stdin: bytes | None = None) -> int: ...
    def answers(self, alias: str, seed: bool) -> bool: ...
    def lists(self, alias: str) -> bool: ...
    def run(self, argv: Sequence[str], env: Mapping[str, str]) -> int: ...
    def sleep(self, seconds: float) -> None: ...
    def clock(self) -> float: ...


def check_launch(compose_text: str, engine: Engine) -> list[str]:
    """The variables the engine's recorded launch should take and doesn't, if any."""
    return [name for name in engine.variables if "${" + name not in compose_text]


def stop_baseline(config: Config) -> str:
    return f"docker stop {shlex.quote(config.baseline_container)}"


def start_candidate(config: Config, engine: Engine, model: str) -> str:
    """The engine's recorded launch, read from stdin, with only the model changed.

    The served name and container are the candidate's, so LiteLLM's
    crew-candidate alias reaches it and nothing clashes with the stopped 27B.
    The 27B's speculative draft is its own, so a candidate runs without one.
    Only the variables the engine's launch takes are set.
    """
    values = {
        "MODEL_PATH": model,
        "SERVED_MODEL_NAME": config.candidate_served_name,
        "SPECULATIVE_ARGS": "",
        "CONTAINER_NAME": config.candidate_container,
    }
    env = {name: values[name] for name in engine.variables}
    assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    return f"env {assignments} docker compose -p {shlex.quote(config.candidate_project)} -f - up -d"


def remove_candidate(config: Config) -> str:
    project = shlex.quote(config.candidate_project)
    container = shlex.quote(config.candidate_container)
    # Down by project; if compose can't, the container by name. Neither fails when it's gone.
    return f"docker compose -p {project} down --timeout 60 || docker rm -f {container}"


def still_running(container: str) -> str:
    """Succeeds while the container runs. It reads Docker's state, never the engine's port."""
    status = shlex.quote("{{.State.Status}}")
    return f'test "$(docker inspect -f {status} {shlex.quote(container)} 2>/dev/null)" = running'


def restore_baseline(config: Config) -> str:
    if config.restore == "container":
        return f"docker start {shlex.quote(config.baseline_container)}"
    if config.restore == "compose":
        return "docker compose -f - up -d"
    return config.start_dflash


def manual_steps(config: Config) -> str:
    """What the Sponsor runs by hand when the restore didn't come back."""
    return "\n".join(
        [
            "Bring the 27B back by hand, on the Spark:",
            f"  {remove_candidate(config)}",
            f"  {restore_baseline(config)}"
            + (
                f"   # with infra's {config.baseline.compose} on stdin"
                if config.restore == "compose"
                else ""
            ),
            "then check it from the Mac, through the proxy:"
            " `uv run crew doctor` in the crew checkout.",
        ]
    )


@contextmanager
def interrupts_raise() -> Iterator[None]:
    """SIGTERM and SIGHUP end the swap the way Ctrl-C does: through the restore."""

    def handler(signum: int, frame: object) -> None:
        raise Interrupted(signal.Signals(signum).name)

    with _handlers({signal.SIGTERM: handler, signal.SIGHUP: handler}):
        yield


@contextmanager
def interrupts_shielded(runner: Runner) -> Iterator[None]:
    """While restoring, no signal stops the restore half-way."""

    def handler(signum: int, frame: object) -> None:
        runner.say(f"swap: {signal.Signals(signum).name} ignored while the 27B is restored")

    with _handlers(dict.fromkeys(SHIELDED, handler)):
        yield


@contextmanager
def _handlers(handlers: dict[signal.Signals, object]) -> Iterator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {signum: signal.signal(signum, h) for signum, h in handlers.items()}  # type: ignore[arg-type]
    try:
        yield
    finally:
        for signum, h in previous.items():
            signal.signal(signum, h)


def wait_until_answers(
    runner: Runner, config: Config, alias: str, seed: bool, container: str
) -> bool:
    """Poll the alias through LiteLLM until it answers, the container exits, or time runs out."""
    deadline = runner.clock() + config.ready_timeout_s
    while True:
        if runner.answers(alias, seed):
            return True
        if runner.remote(still_running(container)) != 0:
            runner.say(f"swap: {container} isn't running; not waiting for it")
            return False
        if runner.clock() + config.poll_s > deadline:
            runner.say(f"swap: {alias} didn't answer in {config.ready_timeout_s:.0f}s")
            return False
        runner.sleep(config.poll_s)


def preflight(
    runner: Runner, config: Config, engine: Engine, launch_text: str, baseline_text: str
) -> str | None:
    """Why the swap mustn't start, or None. Changes nothing."""
    if runner.ticks_running():
        return "a crew tick is running; the swap waits for a pause with no tick"
    for each, text in ((engine, launch_text), (config.baseline, baseline_text)):
        missing = check_launch(text, each)
        if missing:
            return (
                f"infra's {each.name} launch doesn't take {', '.join(missing)}"
                f" ({config.launch_path(each)})"
            )
    if runner.remote("true") != 0:
        return "the Spark doesn't answer ssh"
    if not runner.answers(config.baseline_alias, config.baseline.seed):
        return (
            f"the 27B doesn't answer through LiteLLM as {config.baseline_alias};"
            " nothing to restore to"
        )
    if not runner.lists(config.candidate_alias):
        return f"LiteLLM has no {config.candidate_alias} alias for this key"
    return None


def restore(runner: Runner, config: Config, baseline_text: str) -> bool:
    runner.say("restore 1/3: remove the candidate")
    if runner.remote(remove_candidate(config)) != 0:
        runner.say("swap: the candidate may still be up; restoring the 27B anyway")
    runner.say(f"restore 2/3: bring the 27B back on {config.baseline_engine} ({config.restore})")
    stdin = baseline_text.encode() if config.restore == "compose" else None
    if runner.remote(restore_baseline(config), stdin=stdin) != 0:
        runner.say("swap: the 27B's start command failed; checking whether it answers anyway")
    runner.say(f"restore 3/3: wait until {config.baseline_alias} answers through LiteLLM")
    return wait_until_answers(
        runner, config, config.baseline_alias, config.baseline.seed, config.baseline_container
    )


def command_env(config: Config, engine: Engine, model: str) -> dict[str, str]:
    """What the command is told about the candidate, so a harness sends seeds when it must."""
    return {
        "SWAP_MODEL": model,
        "SWAP_ENGINE": engine.name,
        "SWAP_ALIAS": config.candidate_alias,
        "SWAP_SEED_REQUIRED": "1" if engine.seed else "0",
    }


def swap(
    runner: Runner,
    config: Config,
    engine: Engine,
    model: str,
    command: Sequence[str],
    launch_text: str,
    baseline_text: str,
) -> int:
    """Run `command` with `model` on `engine` on the Spark, and always put the 27B back."""
    reason = preflight(runner, config, engine, launch_text, baseline_text)
    if reason:
        runner.say(f"swap: refused: {reason}")
        return REFUSED

    touched = False
    outcome = 0
    try:
        with interrupts_raise():
            runner.say(f"swap 1/3: stop the 27B ({config.baseline_container})")
            touched = True  # a stop that fails half-way still needs the restore
            if runner.remote(stop_baseline(config)) != 0:
                runner.say("swap: the 27B didn't stop")
                outcome = CANDIDATE_FAILED
            else:
                runner.say(
                    f"swap 2/3: start {model} on {engine.name}, from infra's recorded launch"
                )
                start = start_candidate(config, engine, model)
                if runner.remote(start, stdin=launch_text.encode()) != 0:
                    runner.say("swap: the candidate didn't start")
                    outcome = CANDIDATE_FAILED
                else:
                    runner.say(
                        f"swap 3/3: wait until {config.candidate_alias} answers through LiteLLM"
                    )
                    answered = wait_until_answers(
                        runner,
                        config,
                        config.candidate_alias,
                        engine.seed,
                        config.candidate_container,
                    )
                    if not answered:
                        outcome = CANDIDATE_FAILED
                    else:
                        runner.say(f"run: {shlex.join(command)}")
                        outcome = runner.run(command, command_env(config, engine, model))
                        runner.say(f"run: exited {outcome}")
    except (KeyboardInterrupt, Interrupted) as interrupt:
        runner.say(f"swap: interrupted ({type(interrupt).__name__} {interrupt}); restoring")
        outcome = INTERRUPTED
    finally:
        if touched:
            with interrupts_shielded(runner):
                restored = restore(runner, config, baseline_text)
            if not restored:
                runner.say(f"swap: THE 27B DID NOT COME BACK.\n{manual_steps(config)}")
                outcome = RESTORE_FAILED
            else:
                runner.say(f"swap: the 27B answers again; exiting {outcome}")
    return outcome
