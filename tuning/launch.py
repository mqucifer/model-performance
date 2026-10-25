"""One tuning run: the 27B on SGLang with one setting changed, for one command, then the 27B again.

The Sponsor's limits (mqucifer/model-performance#7, 2026-10-25) are the spec:

  - only this issue's settings, one at a time: `SETTINGS` names them, and a
    launch is refused unless it differs from infra's record in that one flag;
  - only from infra's recorded launch (`compose/spark/sglang/compose.yaml`,
    mqucifer/infra#42): the flag's line is changed in that text, or added
    beside the others when the record doesn't set it, and nothing else is;
  - only when no tick runs: refused while `crew tick` runs, as the swap is;
  - nothing sends a request to SGLang's port: every check goes through LiteLLM;
  - the 27B always comes back with `docker start` on its stopped container,
    after success, a failed command, a launch that never answered, or a signal.

The tuned container keeps the 27B's model, draft and served name, so the crew's
own aliases (`crew-local`, `crew-code-think`) reach it unchanged. It runs as
`spark-tuning`, so it doesn't clash with the stopped 27B, and is removed after
its run. The steps and the restore are the swap's (`swap.core`): only the
launch differs.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

from swap import core
from swap.config import Config

PROJECT = "spark-tuning"
CONTAINER = "spark-tuning"
# A home for rendering the launch on the Mac, so it never reads the Mac's own.
RENDER_HOME = "/home/spark"


@dataclass(frozen=True)
class Setting:
    """A flag this issue may change, and why (mqucifer/model-performance#7's scope)."""

    flag: str
    takes: Callable[[str], object] | None  # None: a flag with no value
    why: str


SETTINGS = {
    s.flag: s
    for s in (
        Setting("--max-running-requests", int, "how many requests run at once"),
        Setting("--mem-fraction-static", float, "the split of memory between weights and KV"),
        Setting("--max-mamba-cache-size", int, "the radix prefix cache's mamba states"),
        Setting("--mamba-radix-cache-strategy", str, "how the radix cache keeps mamba states"),
        Setting("--schedule-policy", str, "the order queued requests run in"),
        Setting("--chunked-prefill-size", int, "chunked prefill"),
        Setting("--enable-mixed-chunk", None, "chunked prefill mixed with decodes"),
        Setting("--speculative-num-draft-tokens", int, "speculative decoding"),
    )
}


class Refused(ValueError):
    """A setting or launch outside the Sponsor's limits."""


def parse(spec: str) -> tuple[Setting, str | None]:
    """`flag=value`, or `flag` for one with no value, checked against `SETTINGS`."""
    flag, eq, value = spec.partition("=")
    flag = "--" + flag.removeprefix("--")
    setting = SETTINGS.get(flag)
    if setting is None:
        raise Refused(f"{flag} isn't one of this issue's settings: {', '.join(SETTINGS)}")
    if setting.takes is None:
        if eq:
            raise Refused(f"{flag} takes no value")
        return setting, None
    if not value or any(c.isspace() for c in value):
        raise Refused(f"{flag} needs one value, as {flag}=VALUE")
    try:
        setting.takes(value)
    except ValueError as error:
        raise Refused(f"{flag}: {error}") from error
    return setting, value


def serving_name(setting: Setting, value: str | None) -> str:
    """The run's `serving` in the results: a short name, such as `mem-fraction-static:0.88`."""
    name = setting.flag.removeprefix("--")
    return name if value is None else f"{name}:{value}"


def tuned(launch_text: str, setting: Setting, value: str | None) -> str:
    """infra's launch with the flag's one line changed, or a line added after `--port`."""
    line = re.compile(rf"^(\s*){re.escape(setting.flag)}(?: \S+)?$", re.MULTILINE)
    found = line.findall(launch_text)
    wanted = setting.flag if value is None else f"{setting.flag} {value}"
    if len(found) > 1:
        raise Refused(f"infra's launch sets {setting.flag} on {len(found)} lines")
    if found:
        return line.sub(lambda m: m.group(1) + wanted, launch_text)
    port = re.compile(r"^(\s*)--port \S+$", re.MULTILINE)
    match = port.search(launch_text)
    if match is None:
        raise Refused("infra's launch has no --port line to add the flag beside")
    at = match.end()
    return launch_text[:at] + "\n" + match.group(1) + wanted + launch_text[at:]


def render(launch_text: str, env: Mapping[str, str]) -> dict[str, Any]:
    """`docker compose config` of a launch on the Mac. It starts nothing."""
    names = (
        "MODEL_PATH",
        "SERVED_MODEL_NAME",
        "SPECULATIVE_ARGS",
        "CONTAINER_NAME",
        "WEIGHTS_CACHE",
    )
    base = {k: v for k, v in os.environ.items() if k not in names}
    out = subprocess.run(
        ["docker", "compose", "-f", "-", "config", "--format", "json"],
        input=launch_text,
        capture_output=True,
        text=True,
        # Docker finds its compose plugin through its config, under the Mac's own home.
        env={
            **base,
            "HOME": RENDER_HOME,
            "DOCKER_CONFIG": os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker")),
            **env,
        },
        check=True,
    )
    return json.loads(out.stdout)


def checker(infra_dir: Path) -> ModuleType:
    """infra's own `check_launch`, which parses a launch's flags as SGLang's argparse does."""
    import importlib.util  # noqa: PLC0415

    path = infra_dir / "compose" / "spark" / "sglang" / "check_launch.py"
    spec = importlib.util.spec_from_file_location("check_launch", path)
    if spec is None or spec.loader is None:
        raise Refused(f"infra's check_launch.py isn't at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def differences(
    recorded: dict[str, Any], candidate: dict[str, Any], flags: Callable[[list[str]], dict]
) -> list[str]:
    """Every difference between two rendered launches but the container's name, flag by flag."""
    a, b = recorded["services"]["sglang"], candidate["services"]["sglang"]
    found = []
    fa, fb = flags(a["command"]), flags(b["command"])
    for flag in sorted(fa.keys() | fb.keys()):
        if fa.get(flag, "<unset>") != fb.get(flag, "<unset>") or (flag in fa) != (flag in fb):
            found.append(flag)
    rest_a = {k: v for k, v in a.items() if k not in ("command", "container_name")}
    rest_b = {k: v for k, v in b.items() if k not in ("command", "container_name")}
    found += [
        f"service.{k}"
        for k in sorted(rest_a.keys() | rest_b.keys())
        if rest_a.get(k) != rest_b.get(k)
    ]
    return found


def prove(
    launch_text: str,
    tuned_text: str,
    setting: Setting,
    flags: Callable[[list[str]], dict],
    rendered: Callable[[str, Mapping[str, str]], dict[str, Any]] = render,
) -> None:
    """Refuse unless the tuned launch differs from infra's in the setting's flag alone."""
    recorded = rendered(launch_text, {})
    candidate = rendered(tuned_text, {"CONTAINER_NAME": CONTAINER})
    found = differences(recorded, candidate, flags)
    if found != [setting.flag]:
        raise Refused(f"the tuned launch must differ in {setting.flag} only; it differs in {found}")
    if candidate["services"]["sglang"]["container_name"] != CONTAINER:
        raise Refused(f"the tuned launch must run as {CONTAINER}")


def tuning_config(config: Config) -> Config:
    """The swap's settings, with the tuned container in the candidate's place."""
    return replace(config, candidate_project=PROJECT, candidate_container=CONTAINER)


def start(name: str) -> str:
    return f"env CONTAINER_NAME={shlex.quote(CONTAINER)} docker compose -p {PROJECT} -f - {name}"


def preflight(runner: core.Runner, config: Config, tuned_text: str) -> str | None:
    """Why the run mustn't start, or None. Changes nothing."""
    if config.restore != "container":
        return "the 27B comes back with docker start only (serving.restore = container)"
    if runner.ticks_running():
        return "a crew tick is running; tuning waits for a pause with no tick"
    if runner.remote("true") != 0:
        return "the Spark doesn't answer ssh"
    if runner.remote(core.still_running(config.baseline_container)) != 0:
        return f"{config.baseline_container} isn't the one running; nothing to restore to"
    if runner.remote(f"! docker container inspect {CONTAINER} >/dev/null 2>&1") != 0:
        return f"{CONTAINER} is already on the Spark; remove it by hand first"
    if not runner.answers(config.baseline_alias, config.baseline.seed):
        return f"the 27B doesn't answer through LiteLLM as {config.baseline_alias}"
    if runner.remote(start("config -q"), stdin=tuned_text.encode()) != 0:
        return "Docker on the Spark won't render the tuned launch"
    return None


def tune(
    runner: core.Runner,
    config: Config,
    serving: str,
    command: list[str],
    tuned_text: str,
) -> int:
    """Run `command` on the tuned 27B, and always put the recorded 27B back."""
    config = tuning_config(config)
    reason = preflight(runner, config, tuned_text)
    if reason:
        runner.say(f"tune: refused: {reason}")
        return core.REFUSED

    touched = False
    outcome = 0
    try:
        with core.interrupts_raise():
            runner.say(f"tune 1/3: stop the 27B ({config.baseline_container})")
            touched = True
            if runner.remote(core.stop_baseline(config)) != 0:
                runner.say("tune: the 27B didn't stop")
                outcome = core.CANDIDATE_FAILED
            else:
                runner.say(f"tune 2/3: start the 27B with {serving}, from infra's recorded launch")
                if runner.remote(start("up -d"), stdin=tuned_text.encode()) != 0:
                    runner.say("tune: the tuned 27B didn't start")
                    outcome = core.CANDIDATE_FAILED
                else:
                    runner.say(
                        f"tune 3/3: wait until {config.baseline_alias} answers through LiteLLM"
                    )
                    if not core.wait_until_answers(
                        runner, config, config.baseline_alias, config.baseline.seed, CONTAINER
                    ):
                        outcome = core.CANDIDATE_FAILED
                    else:
                        runner.say(f"run: {shlex.join(command)}")
                        outcome = runner.run(command, {"TUNE_SERVING": serving})
                        runner.say(f"run: exited {outcome}")
    except (KeyboardInterrupt, core.Interrupted) as interrupt:
        runner.say(f"tune: interrupted ({type(interrupt).__name__} {interrupt}); restoring")
        outcome = core.INTERRUPTED
    finally:
        if touched:
            with core.interrupts_shielded(runner):
                restored = core.restore(runner, config, "")
            if not restored:
                runner.say(f"tune: THE 27B DID NOT COME BACK.\n{core.manual_steps(config)}")
                outcome = core.RESTORE_FAILED
            else:
                runner.say(f"tune: the 27B answers again; exiting {outcome}")
    return outcome


def main(argv: list[str] | None = None) -> int:
    """`tune --set mem-fraction-static=0.88 [--dry-run] -- COMMAND...`"""
    import argparse  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    from common.config import load as load_settings  # noqa: PLC0415
    from swap.cli import infra_commit  # noqa: PLC0415
    from swap.config import ConfigError, load  # noqa: PLC0415
    from swap.runners import DryRunner, RealRunner, read_secrets, say  # noqa: PLC0415

    argv = list(sys.argv[1:] if argv is None else argv)
    split = argv.index("--") if "--" in argv else len(argv)
    own, command = argv[:split], argv[split + 1 :]
    parser = argparse.ArgumentParser(
        prog="tune",
        usage="tune --set FLAG[=VALUE] [--dry-run] -- COMMAND...  (FLAG without its --)",
        description="Serve the 27B with one SGLang setting changed, run COMMAND, "
        "and always bring the recorded 27B back with docker start.",
    )
    parser.add_argument(
        "--set",
        required=True,
        dest="spec",
        help=f"one of {', '.join(f.removeprefix('--') for f in SETTINGS)}",
    )
    parser.add_argument("--dry-run", action="store_true", help="print every step, change nothing")
    parser.add_argument("--infra-dir", type=Path, help="a checkout of mqucifer/infra")
    parser.add_argument(
        "--hosts",
        type=Path,
        default=Path(os.environ.get("INFRA_HOSTS", "~/.config/infra/hosts.env")).expanduser(),
    )
    args = parser.parse_args(own)
    if not command:
        parser.error("give the command to run after --")
    try:
        config = load(infra_dir=args.infra_dir)
        setting, value = parse(args.spec)
        path = config.launch_path(config.baseline)
        launch_text = path.read_text(encoding="utf-8")
        tuned_text = tuned(launch_text, setting, value)
        prove(launch_text, tuned_text, setting, checker(config.infra_dir).flags)
    except (ConfigError, Refused, OSError, subprocess.CalledProcessError) as error:
        say(f"tune: refused: {error}")
        return core.REFUSED
    serving = serving_name(setting, value)
    say(f"tune: {serving} ({setting.why}), launch from infra {infra_commit(config.infra_dir)}")
    say(f"tune: the launch differs from infra's record in {setting.flag} only")

    if args.dry_run:
        runner: core.Runner = DryRunner(config, {tuned_text: f"{path} with {serving}"})
    else:
        try:
            hosts, key = read_secrets(config, args.hosts)
        except LookupError as error:
            say(f"tune: refused: {error}")
            return core.REFUSED
        runner = RealRunner(config, hosts, key)
    began = datetime.now(UTC).isoformat(timespec="seconds")
    outcome = tune(runner, config, serving, command, tuned_text)
    if not args.dry_run:
        # Each restart, for its comment on mqucifer/model-performance#7. Stays on the Mac.
        log = load_settings().records_dir / "tuning" / "restarts.jsonl"
        log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ended = datetime.now(UTC).isoformat(timespec="seconds")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps({"began": began, "ended": ended, "serving": serving, "exit": outcome})
                + "\n"
            )
    return outcome


if __name__ == "__main__":
    sys.exit(main())
