"""One swap: the Spark serves a candidate model for one command, then the 27B again.

The steps, in order (mqucifer/model-performance#2, ADR 0004 in mqucifer/project-print):

  preflight   refuse a model that isn't a hub id, or while a tick runs; the
              Spark answers ssh; the 27B answers through LiteLLM; LiteLLM
              knows the candidate's alias; Docker on the Spark renders the
              candidate's launch, and the 27B's when the restore uses it
  swap        stop the 27B; start the candidate from its engine's launch,
              recorded in infra, with only the model changed; wait until it
              answers through LiteLLM
  run         the given command
  restore     always, once the 27B was touched: remove the candidate and check
              it's gone, bring the 27B back on its own engine, and wait until
              it answers through LiteLLM again
  hold        with --hold, instead of the restore when the candidate doesn't
              answer or the command fails: leave the candidate as it is, say
              what failed and what runs on the Spark, show the candidate's
              last log lines, and print the command that restores. Success
              and signals still restore (mqucifer/model-performance#35)
  prune list  the candidate's image and weights, to prune once unused; nothing
              is deleted

Every model server runs in a container that reads its weights from one cache
(the Sponsor's rule, mqucifer/infra#40), so a candidate leaves nothing behind
but its image and its weights in that cache.

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

import re
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
HELD = 5
INTERRUPTED = 130

LOG_LINES = 80
RESTORE_COMMAND = "uv run swap --restore"

SHIELDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Interrupted(Exception):
    """SIGTERM or SIGHUP arrived; handled like Ctrl-C."""


class Runner(Protocol):
    def say(self, message: str) -> None: ...
    def ticks_running(self) -> bool: ...
    def remote(self, command: str, stdin: bytes | None = None) -> int: ...
    def remote_output(self, command: str) -> tuple[int, str]: ...
    def answers(self, alias: str, seed: bool) -> bool: ...
    def lists(self, alias: str) -> bool: ...
    def run(self, argv: Sequence[str], env: Mapping[str, str]) -> int: ...
    def sleep(self, seconds: float) -> None: ...
    def clock(self) -> float: ...


def check_launch(compose_text: str, engine: Engine) -> list[str]:
    """The variables the engine's recorded launch should take and doesn't, if any."""
    return [name for name in engine.variables if "${" + name not in compose_text]


def launch_env(config: Config, engine: Engine, model: str) -> str:
    """The `env` assignments the candidate's launch takes, and only those.

    The served name and container are the candidate's, so LiteLLM's
    crew-candidate alias reaches it and nothing clashes with the stopped 27B.
    The 27B's speculative draft is its own, so a candidate runs without one.
    The weights cache is under the Spark's home, so $HOME is left to its shell.
    """
    values = {
        "MODEL_PATH": shlex.quote(model),
        "SERVED_MODEL_NAME": shlex.quote(config.candidate_served_name),
        "SPECULATIVE_ARGS": "''",
        "CONTAINER_NAME": shlex.quote(config.candidate_container),
        "WEIGHTS_CACHE": '"$HOME"/' + shlex.quote(config.weights_cache),
    }
    return "env " + " ".join(f"{name}={values[name]}" for name in engine.variables)


def stop_baseline(config: Config) -> str:
    return f"docker stop {shlex.quote(config.baseline_container)}"


def start_candidate(config: Config, engine: Engine, model: str) -> str:
    """The engine's recorded launch, read from stdin, with only the model changed."""
    project = shlex.quote(config.candidate_project)
    return f"{launch_env(config, engine, model)} docker compose -p {project} -f - up -d"


def accepts_candidate(config: Config, engine: Engine, model: str) -> str:
    """Docker on the Spark renders the candidate's launch. It starts nothing."""
    project = shlex.quote(config.candidate_project)
    return f"{launch_env(config, engine, model)} docker compose -p {project} -f - config -q"


def accepts_baseline() -> str:
    """Docker on the Spark renders the 27B's launch with its defaults. It starts nothing."""
    return "docker compose -f - config -q"


def remove_candidate(config: Config) -> str:
    project = shlex.quote(config.candidate_project)
    container = shlex.quote(config.candidate_container)
    # Down by project; if compose can't, the container by name. Then it fails
    # only if the container is still there, which the container rule forbids.
    return (
        f"{{ docker compose -p {project} down --timeout 60 || docker rm -f {container}; }}"
        f" && ! docker container inspect {container} >/dev/null 2>&1"
    )


def still_running(container: str) -> str:
    """Succeeds while the container runs. It reads Docker's state, never the engine's port."""
    status = shlex.quote("{{.State.Status}}")
    return f'test "$(docker inspect -f {status} {shlex.quote(container)} 2>/dev/null)" = running'


def restore_baseline(config: Config) -> str:
    if config.restore == "container":
        return f"docker start {shlex.quote(config.baseline_container)}"
    if config.restore == "compose":
        # The stopped 27B still holds the container's name, and compose won't
        # take it over. `docker rm` without -f removes it only while stopped.
        container = shlex.quote(config.baseline_container)
        return f"{{ docker rm {container} >/dev/null 2>&1 || true; }} && docker compose -f - up -d"
    return config.start_dflash


def containers() -> str:
    """Every container on the Spark, running or not: what a hold leaves there."""
    fmt = shlex.quote("{{.Names}}\t{{.Status}}\t{{.Image}}")
    return f"docker ps -a --format {fmt}"


def candidate_logs(config: Config) -> str:
    return f"docker logs --tail {LOG_LINES} {shlex.quote(config.candidate_container)} 2>&1"


# A line that looks like it carries a token or key: a credential's name with a
# value after it, a bearer header, a known token's shape, or a long run of
# letters and digits in both cases, as keys are (hex digests are one case).
# Engines log "token" in counts and throughputs, so the word alone doesn't
# redact a line.
SECRET_LINE = re.compile(
    r"(?i)("
    r"\b(api|access|secret|private|auth|hf|hub|refresh|session|bearer)[_-]?(key|token)s?\b"
    r"\W{0,3}[:=]"
    r"|\b(secret|password|passwd|credentials?|authorization)\b\W{0,3}[:=]"
    r"|\bbearer\s+\S{8,}"
    r"|\b(hf_|sk-|ghp_|gho_|github_pat_|xox[abp]-)[A-Za-z0-9_-]{8,}"
    r")"
)
OPAQUE = re.compile(r"[A-Za-z0-9]{32,}")
REDACTED = "[redacted: looks like a token or key]"


def looks_secret(line: str) -> bool:
    if SECRET_LINE.search(line):
        return True
    return any(
        re.search("[a-z]", run) and re.search("[A-Z]", run) and re.search("[0-9]", run)
        for run in OPAQUE.findall(line)
    )


def redact(text: str) -> str:
    """The lines as they are, but any that looks like a token or key replaced."""
    return "\n".join(REDACTED if looks_secret(line) else line for line in text.splitlines())


HUB_ID = re.compile(r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*")


def model_problem(model: str) -> str | None:
    """Why the model can't be a candidate's, or None.

    It's a hub id, so its weights land in the one cache the launch mounts. A
    path on the Spark would be outside that cache, or outside the container.
    """
    if not HUB_ID.fullmatch(model):
        return (
            f"the model must be a hub id such as Org/Name, not {model!r}:"
            " every model's weights live in the one cache the containers mount"
        )
    return None


def image_of(launch_text: str) -> str | None:
    found = re.search(r"^\s*image:\s*(\S+)", launch_text, re.MULTILINE)
    return found.group(1) if found else None


def prune_list(
    config: Config, engine: Engine, model: str, launch_text: str, baseline_text: str
) -> list[str]:
    """What the candidate leaves on the Spark, to prune once nothing uses it. Nothing is deleted."""
    found = []
    image = image_of(launch_text)
    if image and image != image_of(baseline_text):
        found.append(f"image {image}")
    found.append(f"weights ~/{config.weights_cache}/models--{model.replace('/', '--')}")
    return found


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
) -> str | None:
    """Poll the alias through LiteLLM until it answers, the container exits, or time runs out.

    None once it answers; otherwise why it didn't.
    """
    deadline = runner.clock() + config.ready_timeout_s
    while True:
        if runner.answers(alias, seed):
            return None
        if runner.remote(still_running(container)) != 0:
            runner.say(f"swap: {container} isn't running; not waiting for it")
            return f"{alias} didn't answer through LiteLLM, and {container} isn't running"
        if runner.clock() + config.poll_s > deadline:
            runner.say(f"swap: {alias} didn't answer in {config.ready_timeout_s:.0f}s")
            return f"{alias} didn't answer through LiteLLM in {config.ready_timeout_s:.0f}s"
        runner.sleep(config.poll_s)


def preflight(
    runner: Runner,
    config: Config,
    engine: Engine,
    model: str,
    launch_text: str,
    baseline_text: str,
) -> str | None:
    """Why the swap mustn't start, or None. Changes nothing."""
    problem = model_problem(model)
    if problem:
        return problem
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
    # Last, as the only checks that send a launch: a launch Docker won't render
    # (a value infra hasn't recorded yet) is refused before the 27B is stopped.
    if runner.remote(accepts_candidate(config, engine, model), stdin=launch_text.encode()) != 0:
        return f"Docker on the Spark won't render infra's {engine.name} launch for the candidate"
    if (
        config.restore == "compose"
        and runner.remote(accepts_baseline(), stdin=baseline_text.encode()) != 0
    ):
        return f"Docker on the Spark won't render infra's {config.baseline.name} launch for the 27B"
    return None


def restore(runner: Runner, config: Config, baseline_text: str) -> bool:
    runner.say("restore 1/3: remove the candidate, and check it's gone")
    if runner.remote(remove_candidate(config)) != 0:
        runner.say(
            f"swap: the candidate's container may still be there; restoring the 27B anyway."
            f" Remove it by hand: docker rm -f {shlex.quote(config.candidate_container)}"
        )
    runner.say(f"restore 2/3: bring the 27B back on {config.baseline_engine} ({config.restore})")
    stdin = baseline_text.encode() if config.restore == "compose" else None
    if runner.remote(restore_baseline(config), stdin=stdin) != 0:
        runner.say("swap: the 27B's start command failed; checking whether it answers anyway")
    runner.say(f"restore 3/3: wait until {config.baseline_alias} answers through LiteLLM")
    problem = wait_until_answers(
        runner, config, config.baseline_alias, config.baseline.seed, config.baseline_container
    )
    return problem is None


def hold(runner: Runner, config: Config, failure: str, restore_command: str) -> None:
    """Leave the candidate as it is, and say what's on the Spark and how to restore."""
    runner.say(f"swap: HOLDING, the 27B is NOT restored: {failure}")
    runner.say(
        f"hold 1/2: what runs on the Spark (the 27B, {config.baseline_container}, is stopped;"
        f" {config.baseline_alias} doesn't answer until the restore)"
    )
    code, listed = runner.remote_output(containers())
    runner.say(listed.rstrip() if code == 0 else f"swap: docker ps failed ({code})")
    runner.say(f"hold 2/2: the last {LOG_LINES} lines of {config.candidate_container}'s log")
    code, logs = runner.remote_output(candidate_logs(config))
    runner.say(redact(logs) if code == 0 else f"swap: docker logs failed ({code})")
    runner.say(f"swap: held, exiting {HELD}. To bring the 27B back: {restore_command}")


def restore_only(runner: Runner, config: Config, baseline_text: str) -> int:
    """`swap --restore`: the swap's own restore, after a hold.

    It refuses nothing about ticks: production is down while the candidate is held.
    """
    with interrupts_shielded(runner):
        restored = restore(runner, config, baseline_text)
    if not restored:
        runner.say(f"swap: THE 27B DID NOT COME BACK.\n{manual_steps(config)}")
        return RESTORE_FAILED
    runner.say("swap: the 27B answers again; exiting 0")
    return 0


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
    hold_on_failure: bool = False,
    restore_command: str = RESTORE_COMMAND,
) -> int:
    """Run `command` with `model` on `engine` on the Spark, and put the 27B back.

    With `hold_on_failure`, a candidate that doesn't answer or a command that
    fails is held for the Sponsor instead: nothing is restored.
    """
    reason = preflight(runner, config, engine, model, launch_text, baseline_text)
    if reason:
        runner.say(f"swap: refused: {reason}")
        return REFUSED

    touched = False
    outcome = 0
    failure = None  # what failed, when a hold may keep the candidate
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
                    failure = wait_until_answers(
                        runner,
                        config,
                        config.candidate_alias,
                        engine.seed,
                        config.candidate_container,
                    )
                    if failure:
                        outcome = CANDIDATE_FAILED
                    else:
                        runner.say(f"run: {shlex.join(command)}")
                        outcome = runner.run(command, command_env(config, engine, model))
                        runner.say(f"run: exited {outcome}")
                        if outcome != 0:
                            failure = f"the command exited {outcome}: {shlex.join(command)}"
    except (KeyboardInterrupt, Interrupted) as interrupt:
        runner.say(f"swap: interrupted ({type(interrupt).__name__} {interrupt}); restoring")
        outcome = INTERRUPTED
        failure = None  # a signal always restores, held or not
    finally:
        if touched and hold_on_failure and failure:
            hold(runner, config, failure, restore_command)
            outcome = HELD
        elif touched:
            with interrupts_shielded(runner):
                restored = restore(runner, config, baseline_text)
            pruning = prune_list(config, engine, model, launch_text, baseline_text)
            runner.say("prune once unused (nothing was deleted): " + "; ".join(pruning))
            if not restored:
                runner.say(f"swap: THE 27B DID NOT COME BACK.\n{manual_steps(config)}")
                outcome = RESTORE_FAILED
            else:
                runner.say(f"swap: the 27B answers again; exiting {outcome}")
    return outcome
