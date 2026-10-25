"""The overlap read: every other call in the window, counted, the run's own left out."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from common import spend

SINCE = datetime(2026, 10, 25, 15, 58, 24, tzinfo=UTC)
UNTIL = datetime(2026, 10, 25, 16, 13, 57, tzinfo=UTC)


def test_other_calls_are_counted_by_who_made_them() -> None:
    asked: list[str] = []

    def read(sql: str) -> str:
        asked.append(sql)
        return "\n".join(
            [
                "mine1|claude-builders|crew-analysis",
                "a|claude-builders|crew-code-think",
                "b|claude-builders|crew-code-think",
                "c|crew|crew-local",
            ]
        )

    found = spend.others(SINCE, UNTIL, {"mine1"}, read=read)
    assert found == Counter({"claude-builders/crew-code-think": 2, "crew/crew-local": 1})
    assert spend.keys(found) == "claude-builders+crew"
    assert "'2026-10-25 16:13:57.000000'" in asked[0] and asked[0].lower().startswith("select")


def test_an_unreadable_log_is_none_not_zero() -> None:
    def fails(sql: str) -> str:
        raise subprocess.CalledProcessError(1, ["docker"])

    assert spend.others(SINCE, UNTIL, set(), read=fails) is None
    assert spend.others(SINCE, UNTIL, set(), read=lambda sql: "") == Counter()
    assert spend.keys(Counter()) is None


def test_a_key_alias_becomes_a_short_name() -> None:
    assert spend.keys(Counter({"a team key/crew-local": 1})) == "a_team_key"


def test_the_run_s_own_calls_are_its_responses(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    lines = [
        {"kind": "llm.finished", "detail": {"response_id": "r1"}},
        {"kind": "llm.started", "detail": {"response_id": "x"}},
        {"kind": "llm.finished", "detail": {}},
    ]
    events.write_text("\n".join(json.dumps(e) for e in lines) + "\nbroken\n")
    assert spend.own_calls(events) == {"r1"}
    assert spend.own_calls(tmp_path / "none.jsonl") == set()
