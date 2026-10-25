"""Replay a story through the crew's own session, at the pinned crew (mqucifer/model-performance#1).

    uv run replay sprint-metrics-662
    uv run replay --all
    uv run replay sprint-metrics-662 --model crew-candidate --cap 150

Checks the story's repository out at its base commit in a fresh worktree, holds its
workspace container as the crew's delivery does, and runs `crew_org.session` on the
story, every model call through LiteLLM on :4000 with the builders' key. At `done`
it runs the crew's gate, the project's autofix then its whole checks, in the same
container.

The run's records (its start, events, diff, gate and result) go to the records
directory on the Mac; its numbers go to `results/benchmark.jsonl`. Nothing reaches
the board, GitHub or crew's `var/events`. Every ending is handled: a run that can't
start is `refused` with why, in a word, and the container and worktree are removed
whatever happens.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.cases import CASES, Case, UnknownCase, case, story
from benchmark.history import history
from common import crew, records, results
from common.config import Settings, load
from common.litellm import Sender, builders_key

SUITE = "benchmark"
TAIL = 3000


class Refused(Exception):
    """A run that couldn't start: `why` in a word for its row, `detail` for its records."""

    def __init__(self, why: str, detail: str) -> None:
        super().__init__(f"{why}: {detail}")
        self.why = why
        self.detail = detail


def clone(work: Path, repo: str) -> Path:
    """The repository, fetched once; every run works in its own worktree of it."""
    path = work / "clones" / repo
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["gh", "repo", "clone", f"mqucifer/{repo}", str(path), "--", "-q"], check=True
        )
    else:
        subprocess.run(["git", "-C", str(path), "fetch", "-q", "origin"], check=True)
    return path


def checkout(work: Path, c: Case, run: str) -> Path:
    repo = clone(work, c.repo)
    path = work / "worktrees" / f"{c.name}-{run}"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(path), c.base],
        check=True,
    )
    return path


def remove(root: Path) -> None:
    """The run's worktree, once its diff is kept. Its clone stays for the next run."""
    common = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"], capture_output=True, text=True
    ).stdout.strip()
    if common:
        repo = (root / common).resolve().parent
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(root)],
            capture_output=True,
        )


def held(root: Path, name: str) -> Any:
    """The workspace container, as the crew's delivery holds it."""
    from crew_org.tools.container import Held  # noqa: PLC0415

    return Held(root, name)


def gate(root: Path, workspace: Any, base: str) -> Any:
    """What the crew runs on the branch at `done`: autofix, then every check."""
    from crew_org.tools.workspace import check  # noqa: PLC0415

    return check(root, held=workspace, since=base)


def record_problem(root: Path) -> str | None:
    """Why crew can't read the project's record at the base, or None.

    Crew falls back to its defaults when it can't: no record in the session's
    start, and its default image, setup and checks. That's a different session
    from the one the case is meant to measure, so the run is refused, not run.
    A project with no record at all is read as crew reads it, without one.
    """
    from crew_org.project import RECORD_PATH, ProjectRecordError, read_record  # noqa: PLC0415

    if not (root / RECORD_PATH).exists():
        return None
    try:
        read_record(root)
    except ProjectRecordError as exc:
        return str(exc)
    return None


def coverage(settings: Settings, c: Case, root: Path) -> Any:
    """The crew's coverage map at the base, if it measured one: read, never built."""
    from crew_org.tools.coverage_map import CoverageMap, with_static  # noqa: PLC0415

    found = sorted((settings.crew_coverage / c.repo).glob(f"{c.base}*.json"))
    return with_static(CoverageMap.from_json(found[0].read_text()), root) if found else None


def diff(root: Path, base: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", base, "--", ".", ":!.crew-home"],
        capture_output=True,
        text=True,
    ).stdout


def replay(
    c: Case,
    settings: Settings,
    send: Sender,
    alias: str,
    *,
    checkout_for: Callable[[Case, str], Path] | None = None,
    workspace_for: Callable[[Path, str], Any] = held,
    gate_for: Callable[[Path, Any, str], Any] = gate,
    results_dir: Path = results.RESULTS,
) -> dict[str, Any]:
    """One case end to end: its row, written to the results once the run has ended."""
    from crew_org import events  # noqa: PLC0415
    from crew_org.session import conversation  # noqa: PLC0415

    checkout_for = checkout_for or (lambda c, run: checkout(settings.work_dir, c, run))
    run = records.run_id()
    out = records.run_dir(settings, SUITE, c.name, run)
    row: dict[str, Any] = {
        "case": c.name,
        "run": run,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "crew_commit": crew.commit(),
        "model_alias": alias,
        "ending": None,
        "stop": None,
        "gate_green": None,
    }
    kept: dict[str, Any] = {"base": c.base, "note": c.note}
    # Each tool call's result, by the crew's own events: a call refused by the session's
    # argument rule (not an object, no such tool, an unknown or missing argument) is one
    # that wasn't well formed.
    tool_results: Counter[str] = Counter()

    def count(event: Any) -> None:
        if event.kind == events.EventKind.TOOL_FINISHED:
            detail = event.detail or {}
            malformed = detail.get("result") == "refused" and str(
                detail.get("rule", "")
            ).startswith("session.arguments")
            tool_results["malformed" if malformed else "ok"] += 1

    send.ticking()
    sink = events.EventSink(out / "events.jsonl")
    sink.subscribe(count)
    events.forward_calls_to(sink)
    began = time.monotonic()
    root: Path | None = None
    workspace: Any = None
    try:
        try:
            root = checkout_for(c, run)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise Refused("checkout", f"{type(exc).__name__}: {exc}") from exc
        unfit = conversation.unfit(root)
        if unfit:
            raise Refused("host_venv", unfit)
        unreadable = record_problem(root)
        if unreadable:
            raise Refused("record_unreadable", unreadable)
        workspace = workspace_for(root, f"bench-{c.name}-{run}")
        started = workspace.start()
        if not started.ok:
            raise Refused("container_start", started.output[-TAIL:])
        setup = workspace.setup()
        if setup is not None and not setup.ok:
            # Once more: a fetch can fail for a moment.
            setup = workspace.setup()
        if setup is not None and not setup.ok:
            ran = f"$ {setup.command}\n(exit {setup.code})\n{setup.output[-TAIL:]}"
            raise Refused("setup_failed", ran)
        kept["setup"] = (
            None
            if setup is None
            else {"command": setup.command, "code": setup.code, "tail": setup.output[-TAIL:]}
        )
        session = conversation.session(
            root,
            story(c),
            workspace,
            workspace.tools,
            coverage=coverage(settings, c, root),
            send=send,
            base=c.base,
            benchmark_run=run,
        )
        (out / "start.md").write_text(session.start, encoding="utf-8")
        ending = session.run()
        row.update(
            {
                "ending": ending.how,
                "stop": ending.stop or ending.why or None,
                "calls": session.calls,
                "model_s": round(session.model_s, 1),
                "edits_applied": len(session.tools.edited),
                "test_runs": len(session.tools.runs),
                "compactions": len(session.compactions),
                "troubles": len(session.troubles),
                "start_chars": len(session.start),
                **{
                    k: session.usage.get(k, 0)
                    for k in (
                        "prompt_tokens",
                        "completion_tokens",
                        "reasoning_tokens",
                        "cached_tokens",
                    )
                },
            }
        )
        kept["session_ending"] = {
            "how": ending.how,
            "stop": ending.stop,
            "why": ending.why,
            "said": ending.said,
            "evidence": ending.evidence,
        }
        if ending.how == "done":
            checked = gate_for(root, workspace, c.base)
            row["gate_green"] = bool(checked.ok)
            gated = [
                {"command": r.command, "code": r.code, "tail": r.output[-TAIL:]}
                for r in checked.results
            ]
            (out / "gate.json").write_text(json.dumps(gated, indent=1), encoding="utf-8")
        (out / "diff.patch").write_text(diff(root, c.base), encoding="utf-8")
    except Refused as refused:
        row["ending"] = "refused"
        row["stop"] = refused.why
        kept["refused"] = refused.detail
    except Exception as exc:  # noqa: BLE001 - a crash still ends the run with a row
        row["ending"] = "crashed"
        row["stop"] = type(exc).__name__
        kept["crashed"] = f"{type(exc).__name__}: {exc}"
    finally:
        if workspace is not None:
            workspace.stop()
        events.reset_bridge()
        if root is not None:
            remove(root)
        row["wall_s"] = round(time.monotonic() - began, 1)
        row["tool_calls"] = sum(tool_results.values())
        row["malformed_tool_calls"] = tool_results["malformed"]
        send.ticking()
        row["concurrent_tick"] = send.tick_seen
        row["tick_calls"] = send.tick_calls
        with contextlib.suppress(OSError):
            kept["history"] = history(settings.crew_events, c.repo, c.card)
        (out / "result.json").write_text(
            json.dumps({**row, **kept}, indent=1, default=str), encoding="utf-8"
        )
    results.append(SUITE, row, results_dir)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="replay", description=__doc__.split("\n\n")[0])
    parser.add_argument("cases", nargs="*", help=f"one or more of: {', '.join(CASES)}")
    parser.add_argument("--all", action="store_true", help="every case, one at a time")
    parser.add_argument("--model", help="a LiteLLM alias in place of the Developer's")
    parser.add_argument("--cap", type=int, help="calls a run may make (default: config's)")
    args = parser.parse_args(argv)
    if bool(args.cases) == args.all:
        parser.error("name the cases, or --all")
    try:
        chosen = list(CASES.values()) if args.all else [case(n) for n in args.cases]
    except UnknownCase as exc:
        parser.error(str(exc.args[0]))

    from crew_org.calls import role_spec  # noqa: PLC0415

    settings = load()
    spec = role_spec("developer")
    alias = args.model or str(spec.get("llm"))
    timeout = float((spec.get("llm_params") or {}).get("timeout", 3600))
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
    failed = 0
    # The crew's sandbox keeps its uv cache under the current directory: the work's.
    with contextlib.chdir(settings.work_dir):
        for c in chosen:
            send = Sender(settings, key, cap=args.cap, alias=args.model, timeout=timeout)
            try:
                row = replay(c, settings, send, alias)
            finally:
                send.close()
            failed += row["ending"] in ("refused", "crashed")
            green = row["gate_green"]
            print(
                f"{c.name}: {row['ending']}"
                f"{' (' + row['stop'] + ')' if row['stop'] else ''}, "
                f"gate {'-' if green is None else 'green' if green else 'red'}, "
                f"{row.get('calls', 0)} calls, {row['tool_calls']} tool calls "
                f"({row['malformed_tool_calls']} malformed), {row.get('model_s', 0)} model s, "
                f"tick during {row['tick_calls']} calls; "
                f"records {settings.records_dir / SUITE / c.name / row['run']}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
