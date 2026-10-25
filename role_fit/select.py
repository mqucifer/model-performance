"""Choosing the cases: E1's own calls, by id, from the crew's events (model-performance#10).

    uv run role-fit select

A case is one model call the crew made during E1 (mqucifer/crew#583) on
sprint-metrics, after mqucifer/crew#633 changed the prompts and before E1 closed:
an `llm.finished` with a `response_id` (LiteLLM's `request_id`) and `try` 1, the
first time a step asked for its answer, so the replay asks what production asked
first. Its production outcome is read from the same record: refused or not (an
`llm.refused` on the same `call_id`), empty, its finish, its tokens and its time.

Each bucket takes, one call per card, the refused calls first (up to half), then
the largest prompts: the failures the crew saw, and the hardest of the rest.
What it prints is pasted into `cases.py`, so every run replays the same calls.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark.spent import events

# E1's window, to the minute as `benchmark.spent.events` compares it: crew#633 merged
# at 17:51:22, and crew#583 closed at 19:42:56 (UTC).
SINCE = "2026-10-11T17:52"
UNTIL = "2026-10-13T19:43"
REPO = "sprint-metrics"


@dataclass(frozen=True)
class Bucket:
    name: str
    group: str  # execution or judgement
    roles: tuple[str, ...]  # as the crew's events name them
    schemas: tuple[str, ...]  # the answer models it asks for, by name
    first: bool | None  # attempt 1 only (True), a later attempt only (False), or any
    take: int


# model-fit-29's plan: 10 Developer calls (6 first, 4 repairs), 5 QA verdicts, 3 criteria
# checks; 3 splits, 3 settles and 2 Architect passes.
BUCKETS = (
    Bucket("dev-first", "execution", ("Developer",), ("FirstOrDone",), True, 6),
    Bucket("dev-repair", "execution", ("Developer",), ("Implementation",), False, 4),
    Bucket("qa-verdict", "execution", ("QA Engineer",), ("QAVerdict",), None, 5),
    Bucket("criteria", "execution", ("QA Engineer",), ("CriteriaCheck",), None, 3),
    Bucket(
        "split",
        "judgement",
        ("Business Analyst", "Product Owner"),
        ("StoryProposal", "EpicProposal"),
        None,
        3,
    ),
    Bucket("settle", "judgement", ("Product Owner",), ("Settlement",), None, 3),
    Bucket("architect", "judgement", ("Architect",), ("DesignNote",), None, 2),
)


def role_key(role: str) -> str:
    """The crew's role name as a short name: `QA Engineer` is `qa_engineer`."""
    return role.lower().replace(" ", "_")


def production(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each first-try answer call in the window, with its outcome as production saw it."""
    calls: dict[str, dict[str, Any]] = {}
    refused: dict[str, bool] = {}
    for event in found:
        detail = event.get("detail") or {}
        call = detail.get("call_id")
        if event.get("kind") == "llm.finished" and detail.get("try") == 1 and call:
            if str(detail.get("repo", "")).endswith(REPO):
                calls[call] = event
        elif event.get("kind") == "llm.refused" and call:
            refused[call] = refused.get(call, False) or bool(detail.get("empty"))
    out = []
    for call, event in calls.items():
        d = event["detail"]
        out.append(
            {
                "id": d["response_id"],
                "role": event.get("role"),
                "card": event.get("card"),
                "schema": str(d.get("output_schema") or "").split(":")[0],
                "attempt": d.get("attempt"),
                "valid": call not in refused,
                "empty": refused.get(call, False),
                "finish": str(d.get("finish_reason")),
                "prompt_tokens": d.get("prompt_tokens"),
                "completion_tokens": d.get("completion_tokens"),
                "reasoning_tokens": d.get("reasoning_tokens"),
                "duration_s": d.get("duration_s"),
            }
        )
    return out


def choose(calls: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Each bucket's cases: refused first (up to half), then the largest prompts, a card once."""
    chosen: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in BUCKETS:
        pool = [
            c
            for c in calls
            if c["role"] in b.roles
            and c["schema"] in b.schemas
            and (b.first is None or (c["attempt"] == 1) == b.first)
        ]
        pool.sort(key=lambda c: (-(c["prompt_tokens"] or 0), c["id"]))
        failed = [c for c in pool if not c["valid"]][: (b.take + 1) // 2]
        cards: set[Any] = set()
        for c in [*failed, *pool]:
            if len(chosen[b.name]) == b.take:
                break
            if c["card"] in cards:
                continue
            cards.add(c["card"])
            chosen[b.name].append(c)
    return dict(chosen)


def main(events_dir: Path) -> int:
    chosen = choose(production(list(events(events_dir, SINCE, UNTIL))))
    for b in BUCKETS:
        for c in chosen.get(b.name, []):
            print(
                f"    Case({c['id']!r}, {b.name!r}, {role_key(c['role'])!r}, {c['card']!r}, "
                f"{c['schema']!r}, {c['attempt']!r}, {c['valid']!r}, {c['empty']!r}, "
                f"{c['finish']!r}, {c['prompt_tokens']!r}, {c['completion_tokens']!r}, "
                f"{c['reasoning_tokens']!r}, {c['duration_s']!r}),"
            )
        if len(chosen.get(b.name, [])) < b.take:
            print(f"    # {b.name}: only {len(chosen.get(b.name, []))} of {b.take} found")
    return 0
