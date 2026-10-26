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
    "suite",  # benchmark, cad_eval, role_fit
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
    # Every other call through the proxy that overlapped the run, from LiteLLM's log
    # (`common/spend.py`), and their key aliases: null if the log couldn't be read.
    "other_calls",
    "other_aliases",
    "arm",  # the one setting changed against the baseline, or null for the baseline
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
        "max_call_reasoning_tokens",  # one call's most, as the arm saw them; null without one
        # What the run's fetched inputs were (`benchmark/inputs.py`): the captured copies'
        # manifest's sha256, and each input's; null for a case with none.
        "inputs_manifest",
        "input_delivery_history",
        "input_design_system_css",
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
        # The harder cases' (mqucifer/model-performance#16): absent from the 30 parts' rows.
        "kind",  # tight, assembly or worded
        "parts_total",  # the case's members, each its own STEP file
        "parts_fit",  # the members that passed every check of their own, fits included
        "load_ok",  # the simplified load check, or null without one or without a `done`
        "fault",  # model, tool, infra or budget, or null for a case that passed
        # Printed as placed, over the members that passed: recorded, never checked.
        "overhang_mm2",  # faces facing down steeper than 45° from vertical, off the bed
        "bridges",  # patches facing straight down, off the bed
        "longest_bridge_mm",  # the longest of their spans
    },
    "role_fit": {
        "stop",  # what ended it, when it isn't `done`: no_request, call_cap, call_failed
        "bucket",  # the kind of call: dev-first, dev-repair, qa-verdict, criteria, ...
        "group",  # execution or judgement
        "role",
        "card",
        "schema",  # the answer model the request asked for
        "form",  # json_schema, two_part or free
        "dated",  # the pinned crew no longer asks for that form
        "seed",
        # The answer, scored in the request's own form (`role_fit/score.py`).
        "valid",
        "why",  # why not valid, in a word
        "empty",
        "runaway",  # run on as whitespace, cut off as crew's call layer does
        "cut",  # stopped at its token limit
        "finish_reason",
        "answer_chars",
        "thinking_chars",
        "hedges_per_10k",  # hedges per 10k characters of thinking
        # The same request in production, from the crew's events and LiteLLM's log.
        "prod_valid",  # crew's verdict: its form and the step's own rules
        "prod_form_valid",  # production's answer scored as the replay's is
        "prod_empty",
        "prod_finish",
        "prod_prompt_tokens",
        "prod_completion_tokens",
        "prod_reasoning_tokens",
        "prod_duration_s",
        "prod_hedges_per_10k",
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
