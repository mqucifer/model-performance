"""The per-role read of crew's event log: counts in the window, and no summary text out."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.spent import spent, table


def log(directory: Path, *events: dict) -> None:
    directory.mkdir(exist_ok=True)
    with (directory / "tick.jsonl").open("w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
        fh.write("not json\n")


def finished(at: str, role: str, reasoning: int, completion: int, **more: object) -> dict:
    detail = {"model": "crew-code-think", "reasoning_tokens": reasoning}
    detail |= {"completion_tokens": completion, "repo": "r", "sprint": "Sprint 1", **more}
    return {"at": at, "kind": "llm.finished", "role": role, "summary": "PROMPT", "detail": detail}


def test_each_role_s_thinking_in_the_window(tmp_path: Path) -> None:
    log(
        tmp_path,
        finished("2026-10-18T23:59:59.1Z", "Developer", 999, 999),
        finished("2026-10-19T00:00:01.5Z", "Developer", 30, 100),
        finished("2026-10-19T01:00:00.0Z", "Developer", 70, 100, finish_reason="length"),
        {"at": "2026-10-19T02:00:00Z", "kind": "session.compacted", "role": "Developer"},
        {"at": "2026-10-19T02:00:00Z", "kind": "llm.empty", "role": "QA Engineer"},
        finished("2026-10-20T00:00:00.0Z", "Developer", 999, 999),
    )
    roles, sprints = spent(tmp_path, "2026-10-19T00:00", "2026-10-20T00:00")
    dev = roles["Developer"]
    assert (dev.reasoning, dev.completion, dev.share) == ([30, 70], 200, 0.5)
    assert (dev.cut_off, dev.compactions) == (1, 1)
    # A role with no finished call isn't a row.
    assert "QA Engineer" not in roles
    assert sprints == {"r Sprint 1": 2}
    text = table(roles)
    assert "| Developer | crew-code-think | 2 | 0.5 | 50, 70, 70 | 100 | 1 | 0 | 1 |" in text
    assert "PROMPT" not in text
