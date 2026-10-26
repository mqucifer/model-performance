"""N benchmark sessions at once on the Spark (mqucifer/model-performance#7).

    uv run concurrent 4
    uv run concurrent 6 --cap 150
    uv run tune --set mem-fraction-static=0.88 -- uv run concurrent 6

Starts N `replay` sessions together, each in its own process (crew's event bridge is
one per process), a few seconds apart so their run ids differ. The benchmark's cases
are taken in order and repeated to make N. Each workspace is capped at 1.5 GiB, the
Sponsor's cap, so 6 to 8 fit in Docker Desktop's 12 GiB.

Before it starts, it refuses while a `crew tick` runs, and when Docker's free memory
can't hold N workspaces: the ceiling it reached is a finding, and nothing else on the
Mac is stopped to make room (the operator, 2026-10-25).

Each session leaves its own benchmark row, tagged with `sessions`, `serving` and the
run's `batch`. The run leaves one row in `results/tuning.jsonl`: its stories, first-time
passes (a green gate at `done`), wall-clock per story, and the Spark's queue, running
requests, cache hits, KV use and time to first token over the run, read from Grafana.
The raw series, and each session's output, go to the records directory on the Mac.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import cycle, islice
from pathlib import Path
from typing import Any

from benchmark.cases import CASES
from common import records, results, spend
from common.config import Settings, load

SUITE = "tuning"
WORKSPACE = "1536m"
GIB = 1024**3
WORKSPACE_GIB = 1.5
# Left free beside the workspaces: the gate's runs and Docker's own use.
RESERVE_GIB = 0.5
STAGGER_S = 3.0
STOP_GRACE_S = 120


UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "KIB": 1024, "MIB": 1024**2, "GIB": GIB}


def size(text: str) -> float:
    """Bytes in one of `docker stats`' sizes, such as 1.1GiB or 512MiB."""
    m = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]+)\s*", text)
    if not m or m.group(2).upper() not in UNITS:
        raise ValueError(f"not a size: {text!r}")
    return float(m.group(1)) * UNITS[m.group(2).upper()]


def docker_free_gib(run: Callable[[list[str]], str] | None = None) -> float:
    """Docker's memory less what its running containers use now, in GiB."""
    run = run or (
        lambda argv: subprocess.run(argv, capture_output=True, text=True, check=True).stdout
    )
    total = float(run(["docker", "info", "--format", "{{.MemTotal}}"]).strip())
    used = sum(
        size(line.split("/")[0])
        for line in run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"]
        ).splitlines()
        if line.strip()
    )
    return round((total - used) / GIB, 2)


def ceiling(free_gib: float) -> int:
    """How many workspaces Docker's free memory holds."""
    return max(int((free_gib - RESERVE_GIB) // WORKSPACE_GIB), 0)


def chosen(n: int, names: Sequence[str] | None = None) -> list[str]:
    """The cases, in order, repeated to make n."""
    return list(islice(cycle(names or list(CASES)), n))


def session_argv(case: str, n: int, serving: str, batch: str, cap: int | None) -> list[str]:
    argv = [sys.executable, "-m", "tuning.session", "--memory", WORKSPACE, "--", case]
    argv += ["--sessions", str(n), "--serving", serving, "--batch", batch]
    return argv + (["--cap", str(cap)] if cap is not None else [])


def start_all(
    argvs: list[list[str]], out: Path, stagger_s: float = STAGGER_S
) -> list[subprocess.Popen[bytes]]:
    started = []
    for i, argv in enumerate(argvs):
        if i:
            time.sleep(stagger_s)
        log = (out / f"{i + 1}-{argv[6]}.log").open("wb")
        started.append(subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT))
    return started


def stop_all(children: list[subprocess.Popen[bytes]]) -> None:
    """Ctrl-C to each session, so its own cleanup removes its workspace; then terminate."""
    for child in children:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
    deadline = time.monotonic() + STOP_GRACE_S
    for child in children:
        try:
            child.wait(timeout=max(deadline - time.monotonic(), 1))
        except subprocess.TimeoutExpired:
            child.terminate()


def batch_rows(batch: str, directory: Path = results.RESULTS) -> list[dict[str, Any]]:
    path = directory / "benchmark.jsonl"
    if not path.exists():
        return []
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    return [r for r in rows if r.get("batch") == batch]


def summary(rows: list[dict[str, Any]], stories: int) -> dict[str, Any]:
    """The run's numbers, from its sessions' rows."""
    walls = [r["wall_s"] for r in rows if r.get("wall_s") is not None]
    speeds = [
        r["completion_tokens"] / r["model_s"]
        for r in rows
        if r.get("model_s") and r.get("completion_tokens")
    ]
    first = rows[0] if rows else {}
    return {
        "crew_commit": first.get("crew_commit"),
        "model_alias": first.get("model_alias"),
        "stories": stories,
        "done": sum(r.get("ending") == "done" for r in rows),
        "gate_green": sum(r.get("gate_green") is True for r in rows),
        "story_wall_s_mean": round(statistics.fmean(walls), 1) if walls else None,
        "story_wall_s_max": max(walls) if walls else None,
        # Model seconds include prefill and queueing, so this is below decode_tps_p50.
        "session_tps_mean": round(statistics.fmean(speeds), 1) if speeds else None,
        **{
            k: sum(r.get(k) or 0 for r in rows)
            for k in (
                "calls",
                "tool_calls",
                "malformed_tool_calls",
                "prompt_tokens",
                "completion_tokens",
                "reasoning_tokens",
                "cached_tokens",
                "tick_calls",
            )
        },
        "model_s": round(sum(r.get("model_s") or 0 for r in rows), 1),
        "concurrent_tick": any(r.get("concurrent_tick") for r in rows),
    }


def concurrent(
    settings: Settings,
    n: int,
    serving: str,
    cap: int | None,
    names: Sequence[str] | None = None,
    free_gib: float | None = None,
    read_grafana: Callable[[Path, float, float], dict[str, Any]] | None = None,
    results_dir: Path = results.RESULTS,
    start: Callable[[list[list[str]], Path], list[Any]] = start_all,
    others: Callable[[datetime, datetime, set[str]], Any] = spend.others,
) -> dict[str, Any]:
    """One concurrent run end to end: its row, written once every session has ended."""
    from tuning import grafana  # noqa: PLC0415

    read_grafana = read_grafana or grafana.copy
    batch = records.run_id()
    out = records.run_dir(settings, SUITE, "concurrent", batch)
    cases = chosen(n, names)
    (out / "plan.json").write_text(
        json.dumps({"sessions": n, "serving": serving, "cases": cases, "cap": cap}),
        encoding="utf-8",
    )
    began_wall, began = time.time(), time.monotonic()
    ending = "done"
    children: list[Any] = []
    try:
        children = start([session_argv(c, n, serving, batch, cap) for c in cases], out)
        for child in children:
            child.wait()
    except KeyboardInterrupt:
        # Each session still ends with its row; the run's row says it was cut short.
        ending = "interrupted"
        stop_all(children)
    ended_wall = time.time()
    rows = batch_rows(batch, results_dir)
    # The calls that overlapped the run and are none of its sessions': the sessions' own
    # rows each count their siblings as other calls, so the run's count leaves them out.
    own: set[str] = set()
    for r in rows:
        own |= spend.own_calls(
            settings.records_dir / "benchmark" / r["case"] / r["run"] / "events.jsonl"
        )
    overlapped = others(
        datetime.fromtimestamp(began_wall, UTC), datetime.fromtimestamp(ended_wall, UTC), own
    )
    row = {
        "run": batch,
        "at": datetime.fromtimestamp(began_wall, UTC).isoformat(timespec="seconds"),
        "sessions": n,
        "serving": serving,
        "workspace_memory": WORKSPACE,
        "docker_free_gib": free_gib,
        "ending": ending,
        "wall_s": round(time.monotonic() - began, 1),
        **summary(rows, len(cases)),
        "other_calls": None if overlapped is None else sum(overlapped.values()),
        "other_aliases": spend.keys(overlapped) if overlapped else None,
        **read_grafana(out, began_wall, ended_wall),
    }
    results.append(SUITE, row, results_dir)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concurrent", description=__doc__.split("\n\n")[0])
    parser.add_argument("sessions", type=int, help="how many sessions at once")
    parser.add_argument("--cap", type=int, help="calls each session may make (default: config's)")
    parser.add_argument(
        "--cases", nargs="+", choices=list(CASES), help="the cases to cycle through"
    )
    parser.add_argument(
        "--serving",
        default=os.environ.get("TUNE_SERVING", "record"),
        help="the Spark's setting, as `tune` sets it (default: record)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.sessions <= 8:
        parser.error("from 1 to 8 sessions")

    from swap.runners import ticks_running  # noqa: PLC0415

    if ticks_running():
        print("concurrent: refused: a crew tick is running", file=sys.stderr)
        return 2
    try:
        free = docker_free_gib()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(
            f"concurrent: refused: Docker's free memory unread ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    most = ceiling(free)
    print(f"concurrent: Docker has {free} GiB free: room for {most} workspaces of {WORKSPACE}")
    if args.sessions > most:
        print(
            f"concurrent: refused: {args.sessions} sessions need"
            f" {args.sessions * WORKSPACE_GIB + RESERVE_GIB} GiB; the ceiling is {most}",
            file=sys.stderr,
        )
        return 2

    def stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt(signal.Signals(signum).name)

    # SIGTERM (from `tune`, or a kill) ends the run as Ctrl-C does: each session cleans up.
    signal.signal(signal.SIGTERM, stop)
    settings = load()
    row = concurrent(settings, args.sessions, args.serving, args.cap, args.cases, free)
    print(
        f"concurrent {row['run']}: {row['sessions']} sessions on {row['serving']}:"
        f" {row['done']} done, {row['gate_green']} gate green,"
        f" {row['story_wall_s_mean']} s per story (max {row['story_wall_s_max']}),"
        f" TTFT p50 {row['ttft_p50_s']} s p95 {row['ttft_p95_s']} s,"
        f" queue max {row['queue_max']}, running max {row['running_max']},"
        f" cache hits {row['cache_hit_mean']}, KV max {row['kv_use_max']};"
        f" records {settings.records_dir / SUITE / 'concurrent' / row['run']}"
    )
    return 0 if row["done"] == row["stories"] else 1


if __name__ == "__main__":
    sys.exit(main())
