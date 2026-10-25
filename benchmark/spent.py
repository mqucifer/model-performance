"""What the crew already spent thinking, per role, from its event log (model-performance#5).

    uv run python -m benchmark.spent --since 2026-10-19T00:00Z --until 2026-10-25T15:44Z

Observed in production, not a controlled arm: each role's calls ran on its own
alias, story and load. It reads crew's `var/events` read-only and makes no model
call. `llm.finished` carries each call's counts. `completion_tokens` includes
`reasoning_tokens`, so the answer is their difference.

Prints counts only, never an event's summary, which can hold prompt text. The
Developer's controlled numbers are the benchmark's (`replay --arm`); replaying calls
per role through other models is mqucifer/model-performance#10's.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.config import load


@dataclass
class Role:
    models: Counter[str] = field(default_factory=Counter)
    reasoning: list[int] = field(default_factory=list)
    completion: int = 0
    cut_off: int = 0
    empty: int = 0
    compactions: int = 0

    @property
    def share(self) -> float | None:
        return round(sum(self.reasoning) / self.completion, 2) if self.completion else None


def events(directory: Path, since: str, until: str) -> Iterator[dict[str, Any]]:
    """Every event in the window, from every log in the directory; a broken line is skipped."""
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and since <= str(event.get("at", ""))[:16] < until:
                    yield event


def spent(directory: Path, since: str, until: str) -> tuple[dict[str, Role], Counter[str]]:
    """Each role's thinking in the window, and the window's calls by repository and sprint."""
    roles: dict[str, Role] = defaultdict(Role)
    sprints: Counter[str] = Counter()
    for event in events(directory, since, until):
        detail = event.get("detail") or {}
        role = roles[str(event.get("role"))]
        kind = event.get("kind")
        if kind == "llm.finished":
            role.models[str(detail.get("model"))] += 1
            role.reasoning.append(int(detail.get("reasoning_tokens") or 0))
            role.completion += int(detail.get("completion_tokens") or 0)
            role.cut_off += detail.get("finish_reason") == "length"
            sprints[f"{detail.get('repo')} {detail.get('sprint')}"] += 1
        elif kind == "llm.empty":
            role.empty += 1
        elif kind == "session.compacted":
            role.compactions += 1
    return {name: r for name, r in roles.items() if r.reasoning}, sprints


def table(roles: dict[str, Role]) -> str:
    lines = [
        "| Role | Alias | Calls | Reasoning / completion | Reasoning per call: median, p90, max "
        "| Answer tokens | Cut off | Empty | Compactions |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in sorted(roles.items(), key=lambda kv: -len(kv[1].reasoning)):
        spread = sorted(r.reasoning)
        p90 = spread[max(0, round(0.9 * len(spread)) - 1)]
        lines.append(
            f"| {name} | {', '.join(sorted(r.models))} | {len(spread):,} | {r.share} "
            f"| {statistics.median(spread):,.0f}, {p90:,}, {spread[-1]:,} "
            f"| {r.completion - sum(spread):,} | {r.cut_off} | {r.empty} | {r.compactions} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spent", description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", required=True, help="UTC, as 2026-10-19T00:00Z")
    parser.add_argument("--until", required=True, help="UTC, exclusive")
    args = parser.parse_args(argv)
    directory = load().crew_events
    # To the minute: an event's time carries seconds and more.
    roles, sprints = spent(directory, args.since[:16], args.until[:16])
    print(table(roles))
    print()
    calls = ", ".join(f"{k} {v}" for k, v in sorted(sprints.items()))
    print(f"Calls by repository and sprint: {calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
