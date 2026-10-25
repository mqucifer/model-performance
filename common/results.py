"""The numbers a run leaves in the repository: one row per run in `results/<suite>.jsonl`.

A row holds numbers, flags and short names only, never a prompt or an answer
(ADR 0004 in mqucifer/project-print): those stay in the run's records on the
Mac. Every field is declared here, so a row with an undeclared field, or text
that isn't a short name, is refused when it's written and fails CI if it's
committed (`scripts/check_no_prompts.py`). Standard library only: CI runs the
check without the project's dependencies.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).parents[1] / "results"

# What every suite's row has.
SHARED = {
    "suite",  # benchmark, cad_eval
    "case",
    "run",  # the run's id, which names its records directory
    "at",  # when it started, UTC
    "crew_commit",  # the crew commit the run imported
    "model_alias",  # the LiteLLM alias it called
    "ending",  # how it ended, in a word
    "calls",
    "tool_calls",
    "malformed_tool_calls",  # not well formed: bad JSON, no such tool, wrong arguments
    "model_s",
    "wall_s",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "concurrent_tick",  # whether a crew tick ran at any point: it shares the model
    "tick_calls",  # the calls made while one ran
}
# Each suite's own fields, beside the shared ones.
SUITES: dict[str, set[str]] = {
    "benchmark": {
        "stop",  # the stop that ended a blocked session, if one did
        "gate_green",  # the crew's gate at `done`, or null without a `done`
        "edits_applied",
        "test_runs",
        "compactions",
        "troubles",  # empty, cut-off or malformed answers
        "start_chars",
        "record_authored",  # the session read the case's authored record, not the base's own
        "arm",  # the one setting changed (benchmark/arms.py), or null for the baseline
        "max_call_reasoning_tokens",  # one call's most, as the arm saw them; null without one
    },
    "cad_eval": {
        "tier",  # the part's difficulty, 1 to 5
        "stop",  # what ended it, in a word, when it isn't `done`
        "image",  # the CadQuery image's tag
        # Tool calls in BFCL's categories, beside the shared malformed count.
        "ill_typed_tool_calls",  # well formed by crew's rule, but a value of the wrong type
        "failed_tool_calls",  # well formed, but the tool couldn't do what it asked
        "reliable_tool_calls",
        "tool_reliability",  # reliable / tool_calls, or null with none
        "writes",
        "runs",
        "inspects",
        # The part, checked at `done`, or null without one.
        "compiles",
        "closed_mesh",
        "within_tolerance",
        "checks_passed",
        "checks_total",
        "calls_to_done",  # the calls a part took to `done`, or null without one
    },
}
# A short name: an id, a commit, a time, an alias. No spaces, so no sentence fits.
NAME = re.compile(r"[A-Za-z0-9_.:@/+-]{1,80}")


class NotNumbers(ValueError):
    """A row that holds more than numbers and short names."""


def problems(row: Any) -> list[str]:
    """What keeps `row` from being a results row; empty when it is one."""
    if not isinstance(row, dict):
        return ["a row is a JSON object"]
    suite = row.get("suite")
    if suite not in SUITES:
        return [f"suite must be one of {sorted(SUITES)}"]
    found = []
    for key in sorted(set(row) - SHARED - SUITES[suite]):
        found.append(f"{key}: not a declared field")
    for key, value in row.items():
        if value is None or isinstance(value, bool | int | float):
            continue
        if isinstance(value, str) and NAME.fullmatch(value):
            continue
        found.append(f"{key}: only numbers, flags and short names")
    return found


def append(suite: str, row: dict[str, Any], directory: Path = RESULTS) -> Path:
    """Add one run's row to its suite's file, refused if it's more than numbers."""
    row = {"suite": suite, **row}
    found = problems(row)
    if found:
        raise NotNumbers("; ".join(found))
    path = directory / f"{suite}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path
