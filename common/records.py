"""Where a run's records go: under the records directory, on the Mac, readable by its owner only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from common.config import Settings


def run_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def run_dir(settings: Settings, suite: str, case: str, run: str) -> Path:
    """A new directory for one run. One that exists already is refused, never written over."""
    path = settings.records_dir / suite / case / run
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.mkdir(mode=0o700)
    return path


def new_run(settings: Settings, suite: str, case: str) -> tuple[str, Path]:
    """A run id and its new records directory. Ids are to the second, so two runs of a
    case that start in the same second, in two processes, would share one: the second
    takes the next free suffix (`-2`, `-3`, ...), and nothing is ever written over."""
    base = run_id()
    for n in range(1, 100):
        run = base if n == 1 else f"{base}-{n}"
        try:
            return run, run_dir(settings, suite, case, run)
        except FileExistsError:
            continue
    raise FileExistsError(f"no free run id for {suite}/{case} at {base}")
