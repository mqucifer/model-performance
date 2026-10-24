"""`swap <model> [--dry-run] -- <command>`: run a command with another model on the Spark."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from swap import core
from swap.config import DEFAULT_CONFIG, ConfigError, load
from swap.runners import DryRunner, RealRunner, read_secrets, say


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Everything after the first -- is the command, untouched by the swap's own options.
    split = argv.index("--") if "--" in argv else len(argv)
    own, command = argv[:split], argv[split + 1 :]
    parser = argparse.ArgumentParser(
        prog="swap",
        usage="swap MODEL [--dry-run] [options] -- COMMAND...",
        description=(
            "Stop the Spark's 27B, serve MODEL from infra's recorded launch, run COMMAND, "
            "and always bring the 27B back. Every check goes through LiteLLM on :4000."
        ),
    )
    parser.add_argument("model", help="the candidate's model path, as SGLang's --model-path has it")
    parser.add_argument("--dry-run", action="store_true", help="print every step, change nothing")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--infra-dir", type=Path, help="a checkout of mqucifer/infra")
    parser.add_argument(
        "--hosts",
        type=Path,
        default=Path(os.environ.get("INFRA_HOSTS", "~/.config/infra/hosts.env")).expanduser(),
        help="infra's address file ($INFRA_HOSTS)",
    )
    args = parser.parse_args(own)
    args.command = command
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


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    try:
        config = load(args.config, infra_dir=args.infra_dir)
    except ConfigError as error:
        say(f"swap: refused: {error}")
        return core.REFUSED
    if not config.compose_path.is_file():
        say(
            f"swap: refused: infra's recorded launch isn't at {config.compose_path} "
            "(recorded by mqucifer/infra#40)"
        )
        return core.REFUSED
    compose_text = config.compose_path.read_text(encoding="utf-8")
    say(f"swap: {args.model}, launch from infra {infra_commit(config.infra_dir)}")

    if args.dry_run:
        runner: core.Runner = DryRunner(config)
    else:
        try:
            hosts, key = read_secrets(config, args.hosts)
        except LookupError as error:
            say(f"swap: refused: {error}")
            return core.REFUSED
        runner = RealRunner(config, hosts, key)
    return core.swap(runner, config, args.model, args.command, compose_text)
