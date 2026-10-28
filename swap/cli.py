"""`swap <model> [--hold] [--dry-run] -- <command>`: run a command with another model on the Spark.

`swap --restore` brings the 27B back after a hold.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from swap import core
from swap.config import DEFAULT_CONFIG, Config, ConfigError, load
from swap.runners import DryRunner, RealRunner, read_secrets, say


def default_hosts() -> Path:
    return Path(os.environ.get("INFRA_HOSTS", "~/.config/infra/hosts.env")).expanduser()


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Everything after the first -- is the command, untouched by the swap's own options.
    split = argv.index("--") if "--" in argv else len(argv)
    own, command = argv[:split], argv[split + 1 :]
    parser = argparse.ArgumentParser(
        prog="swap",
        usage=(
            "swap MODEL [--engine ENGINE] [--hold] [--dry-run] [options] -- COMMAND...\n"
            "       swap --restore [--dry-run] [options]"
        ),
        description=(
            "Stop the Spark's 27B, serve MODEL on ENGINE from infra's recorded launch, "
            "run COMMAND, and bring the 27B back. Every check goes through LiteLLM "
            "on :4000."
        ),
    )
    parser.add_argument(
        "model", nargs="?", help="the candidate's model path, as SGLang's --model-path has it"
    )
    parser.add_argument(
        "--engine", default="sglang", help="the engine in config.toml's [engines] (sglang)"
    )
    parser.add_argument(
        "--hold",
        action="store_true",
        help=(
            "if the candidate doesn't answer or COMMAND fails, leave the candidate up and"
            " don't restore; success and signals still restore"
        ),
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="bring the 27B back after a hold: no MODEL, no COMMAND",
    )
    parser.add_argument("--dry-run", action="store_true", help="print every step, change nothing")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--infra-dir", type=Path, help="a checkout of mqucifer/infra")
    parser.add_argument(
        "--hosts",
        type=Path,
        default=default_hosts(),
        help="infra's address file ($INFRA_HOSTS)",
    )
    args = parser.parse_args(own)
    args.command = command
    if args.restore:
        if args.model or args.command or args.hold:
            parser.error("--restore takes no MODEL, no COMMAND and no --hold")
        return args
    if not args.model:
        parser.error("give the MODEL, or --restore")
    if not args.command:
        parser.error("give the command to run after --")
    if not args.model.strip() or any(c.isspace() for c in args.model):
        parser.error("the model is one path, with no spaces")
    return args


def infra_commit(infra_dir: Path) -> str:
    """The infra commit the launch is read from, marked when the checkout has changes."""
    try:
        head = subprocess.run(
            ["git", "-C", str(infra_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(infra_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{' with local changes' if dirty else ''}"


def restore_command(args: argparse.Namespace) -> str:
    """The one command that restores after this hold, with this run's own settings."""
    parts = ["uv", "run", "swap", "--restore"]
    if args.config != DEFAULT_CONFIG:
        parts += ["--config", str(args.config)]
    if args.infra_dir:
        parts += ["--infra-dir", str(args.infra_dir)]
    if args.hosts != default_hosts():
        parts += ["--hosts", str(args.hosts)]
    return shlex.join(parts)


def runner_for(args: argparse.Namespace, config: Config, launches: dict[str, Path]) -> core.Runner:
    """The dry runner, or the real one; LookupError when a secret isn't set."""
    if args.dry_run:
        return DryRunner(config, launches)
    hosts, key = read_secrets(config, args.hosts)
    return RealRunner(config, hosts, key)


def restore(args: argparse.Namespace, config: Config) -> int:
    """`swap --restore`: the 27B's launch from infra is needed only when the restore uses it."""
    baseline = config.baseline
    path = config.launch_path(baseline)
    baseline_text = ""
    if config.restore == "compose":
        if not path.is_file():
            say(f"swap: refused: infra's {baseline.name} launch isn't at {path}")
            return core.REFUSED
        baseline_text = path.read_text(encoding="utf-8")
    say(f"swap: restore the 27B on {baseline.name} ({config.restore})")
    try:
        runner = runner_for(args, config, {baseline_text: baseline.compose})
    except LookupError as error:
        say(f"swap: refused: {error}")
        return core.REFUSED
    return core.restore_only(runner, config, baseline_text)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if args.restore:
        try:
            return restore(args, load(args.config, infra_dir=args.infra_dir))
        except ConfigError as error:
            say(f"swap: refused: {error}")
            return core.REFUSED
    try:
        config = load(args.config, infra_dir=args.infra_dir)
        engine = config.engine(args.engine)
    except ConfigError as error:
        say(f"swap: refused: {error}")
        return core.REFUSED
    texts = []
    for each in (engine, config.baseline):
        path = config.launch_path(each)
        if not path.is_file():
            say(
                f"swap: refused: infra's {each.name} launch isn't at {path}"
                " (recorded by mqucifer/infra#40)"
            )
            return core.REFUSED
        texts.append(path.read_text(encoding="utf-8"))
    launch_text, baseline_text = texts
    say(f"swap: {args.model} on {engine.name}, launch from infra {infra_commit(config.infra_dir)}")

    launches = {launch_text: engine.compose, baseline_text: config.baseline.compose}
    try:
        runner = runner_for(args, config, launches)
    except LookupError as error:
        say(f"swap: refused: {error}")
        return core.REFUSED
    hint = restore_command(args)
    outcome = core.swap(
        runner,
        config,
        engine,
        args.model,
        args.command,
        launch_text,
        baseline_text,
        hold_on_failure=args.hold,
        restore_command=hint,
    )
    if args.dry_run and args.hold and outcome == 0:
        say(
            "[dry-run] with --hold, if the candidate doesn't answer or the command fails,"
            " the restore above doesn't run; instead:"
        )
        core.hold(runner, config, "(what failed)", hint)
    return outcome
