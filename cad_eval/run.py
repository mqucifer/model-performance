"""Run parts of the CAD-code evaluation on a model (mqucifer/model-performance#3).

    uv run cad-eval spacer l-bracket
    uv run cad-eval --first          # one part per tier: the first run
    uv run cad-eval --all --model crew-candidate --cap 40

Each part gets a fresh directory and its own container from the CadQuery image, held
by crew's sandbox, and a session with the Developer's model through LiteLLM on :4000
with the builders' key. At `done` its script is run again from a clean start and what
it writes is checked: it compiles, its mesh is closed, its dimensions are within
tolerance.

The run's records (its events, the files it wrote, its checks and result) go to the
records directory on the Mac; its numbers go to `results/cad_eval.jsonl`. Every ending
is handled: a run that can't start is `refused` with why, in a word, and the container
and directory are removed whatever happens.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cad_eval import checks, container
from cad_eval.parts import FIRST, PARTS, Part, UnknownPart, part
from cad_eval.session import Session
from cad_eval.tools import PartTools
from common import crew, records, results
from common.config import Settings, load
from common.litellm import Sender, builders_key

SUITE = "cad_eval"
# A part's calls (the operator, 2026-10-25): 20 ended two of the first run's five, so it
# starts high and comes down from each part's `calls_to_done`.
CAP_PER_PART = 40


class Refused(Exception):
    def __init__(self, why: str, detail: str) -> None:
        super().__init__(f"{why}: {detail}")
        self.why = why
        self.detail = detail


def directory(settings: Settings, p: Part, run: str) -> Path:
    path = settings.work_dir / SUITE / f"{p.name}-{run}"
    path.mkdir(parents=True)
    return path


def keep(source: Path, out: Path) -> None:
    """The files the session left, into its records: they're the model's answers."""
    for found in source.rglob("*"):
        relative = found.relative_to(source)
        if found.is_file() and relative.parts[0] != ".crew-home":
            target = out / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found, target)


def evaluate(
    p: Part,
    settings: Settings,
    send: Sender,
    alias: str,
    *,
    max_tokens: int = 65536,
    workspace_for: Callable[[Path, str], Any] = container.held,
    image_id: Callable[[], str | None] = container.image_id,
    results_dir: Path = results.RESULTS,
) -> dict[str, Any]:
    """One part end to end: its row, written to the results once the run has ended."""
    run = records.run_id()
    out = records.run_dir(settings, SUITE, p.name, run)
    row: dict[str, Any] = {
        "case": p.name,
        "tier": p.tier,
        "run": run,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "crew_commit": crew.commit(),
        "model_alias": alias,
        "image": container.IMAGE,
        "ending": None,
        "stop": None,
        "compiles": None,
        "closed_mesh": None,
        "within_tolerance": None,
        "checks_passed": None,
        "checks_total": None,
        "calls_to_done": None,
    }
    kept: dict[str, Any] = {}
    send.ticking()
    began = time.monotonic()
    root: Path | None = None
    workspace: Any = None
    session: Session | None = None
    try:
        kept["image_id"] = image_id()
        if kept["image_id"] is None:
            raise Refused("no_image", f"{container.IMAGE} isn't built: cad_eval/image/build.sh")
        root = directory(settings, p, run)
        workspace = workspace_for(root, f"cad-{p.name}-{run}")
        started = workspace.start()
        if not started.ok:
            raise Refused("container_start", started.output[-3000:])
        tools = PartTools(root, workspace)
        session = Session(p.spec(), tools, send, alias, out / "events.jsonl", max_tokens=max_tokens)
        ending = session.run()
        row["ending"], row["stop"] = ending.how, ending.stop or None
        row["calls_to_done"] = session.calls if ending.how == "done" else None
        kept["said"] = ending.said
        if ending.how == "done":
            final = tools.final(str(ending.said["script"]), p.probes(), p.mate)
            measured = final["measured"]
            found = checks.dimensions(p, measured)
            row["compiles"] = final["code"] == 0 and checks.valid(measured)
            row["closed_mesh"] = checks.closed(measured)
            row["within_tolerance"] = all(c.ok for c in found)
            row["checks_passed"] = sum(c.ok for c in found)
            row["checks_total"] = len(found)
            final["checks"] = [asdict(c) for c in found]
            (out / "checks.json").write_text(json.dumps(final, indent=1), encoding="utf-8")
    except Refused as refused:
        row["ending"], row["stop"] = "refused", refused.why
        kept["refused"] = refused.detail
    except Exception as exc:  # noqa: BLE001 - a crash still ends the run with a row
        row["ending"], row["stop"] = "crashed", type(exc).__name__
        kept["crashed"] = f"{type(exc).__name__}: {exc}"
    finally:
        if workspace is not None:
            workspace.stop()
        if root is not None:
            keep(root, out)
            shutil.rmtree(root, ignore_errors=True)
        row.update(counts(session))
        row["wall_s"] = round(time.monotonic() - began, 1)
        send.ticking()
        row["concurrent_tick"] = send.tick_seen
        row["tick_calls"] = send.tick_calls
        (out / "result.json").write_text(
            json.dumps({**row, **kept}, indent=1, default=str), encoding="utf-8"
        )
    results.append(SUITE, row, results_dir)
    return row


def counts(session: Session | None) -> dict[str, Any]:
    """The session's numbers, zero for one that never started."""
    outcomes = session.outcomes if session else {}
    by_tool = session.by_tool if session else {}
    usage = session.usage if session else {}
    total = sum(outcomes.values())
    return {
        "calls": session.calls if session else 0,
        "model_s": round(session.model_s, 1) if session else 0.0,
        "tool_calls": total,
        "malformed_tool_calls": outcomes.get("malformed", 0),
        "ill_typed_tool_calls": outcomes.get("ill_typed", 0),
        "failed_tool_calls": outcomes.get("failed", 0),
        "reliable_tool_calls": outcomes.get("ok", 0),
        "tool_reliability": round(outcomes.get("ok", 0) / total, 4) if total else None,
        "writes": by_tool.get("write", 0),
        "runs": by_tool.get("run", 0),
        "inspects": by_tool.get("inspect", 0),
        **{
            k: usage.get(k, 0)
            for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens")
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad-eval", description=__doc__.split("\n\n")[0])
    parser.add_argument("parts", nargs="*", help=f"one or more of: {', '.join(PARTS)}")
    chosen_by = parser.add_mutually_exclusive_group()
    chosen_by.add_argument("--first", action="store_true", help="one part per tier")
    chosen_by.add_argument("--all", action="store_true", help="every part, one at a time")
    parser.add_argument("--model", help="a LiteLLM alias in place of the Developer's")
    parser.add_argument("--cap", type=int, default=CAP_PER_PART, help="calls a part may make")
    parser.add_argument(
        "--total", type=int, help="calls the whole run may make (default: the cap for each part)"
    )
    args = parser.parse_args(argv)
    if bool(args.parts) == (args.first or args.all):
        parser.error("name the parts, or --first, or --all")
    try:
        names = list(PARTS) if args.all else list(FIRST) if args.first else args.parts
        chosen = [part(n) for n in names]
    except UnknownPart as exc:
        parser.error(str(exc.args[0]))
    total = args.total if args.total is not None else args.cap * len(chosen)

    from crew_org.calls import role_spec  # noqa: PLC0415

    from swap.runners import ticks_running  # noqa: PLC0415

    if ticks_running():
        print("refused: a crew tick is running, and it shares the model", file=sys.stderr)
        return 2
    if container.image_id() is None:
        print(f"refused: {container.IMAGE} isn't built: cad_eval/image/build.sh", file=sys.stderr)
        return 2
    settings = load()
    spec = role_spec("developer")
    alias = args.model or str(spec.get("llm"))
    params = spec.get("llm_params") or {}
    timeout = float(params.get("timeout", 3600))
    max_tokens = int(params.get("max_tokens", 65536))
    try:
        key = builders_key(settings)
    except (LookupError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    preflight = Sender(settings, key, cap=0)
    try:
        if not preflight.lists(alias):
            print(f"refused: LiteLLM doesn't list {alias} for the builders' key", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - any failure to reach the proxy refuses the run
        print(f"refused: LiteLLM on :4000 didn't answer ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        preflight.close()

    settings.work_dir.mkdir(parents=True, exist_ok=True)
    failed = spent = 0
    # The crew's sandbox keeps its uv cache under the current directory: the work's.
    with contextlib.chdir(settings.work_dir):
        for p in chosen:
            cap = min(args.cap, total - spent)
            if cap < 1:
                print(f"{p.name}: not run, the run's {total} calls are spent")
                continue
            send = Sender(settings, key, cap=cap, alias=args.model, timeout=timeout)
            try:
                row = evaluate(p, settings, send, alias, max_tokens=max_tokens)
            finally:
                spent += send.calls
                send.close()
            failed += row["ending"] in ("refused", "crashed")
            print(
                f"{p.name} (tier {p.tier}): {row['ending']}"
                f"{' (' + row['stop'] + ')' if row['stop'] else ''}; "
                f"compiles {row['compiles']}, closed {row['closed_mesh']}, "
                f"within {row['within_tolerance']} "
                f"({row['checks_passed']}/{row['checks_total']}); "
                f"{row['calls']} calls, {row['tool_calls']} tool calls, "
                f"reliability {row['tool_reliability']} "
                f"({row['malformed_tool_calls']} malformed, {row['ill_typed_tool_calls']} "
                f"ill-typed, {row['failed_tool_calls']} failed); {row['model_s']} model s; "
                f"records {settings.records_dir / SUITE / p.name / row['run']}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
