"""The benchmark's cases: stories that really failed, at the commit their first attempt
started from, with the story as it stood then (from crew#778's session replay).

Each story's text is kept in `cases/<case>.md`, fetched once from the issue's edit
history, so every run reads the same text whatever the issue says now:

    uv run python -m benchmark.cases --fetch

A case may also carry `cases/<case>.project.yaml`, the project's record in the format
the pinned crew reads, for a base whose own record is in an older one. It's an
authored input: the repository's own format migration of the same record, trimmed
to what was true at the base (`results/README.md` says how).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STORIES = Path(__file__).with_name("cases")


@dataclass(frozen=True)
class Case:
    repo: str
    card: int
    # The commit the first attempt started from: its pull request's first commit's
    # parent where it opened one, else the default branch's head before its first call.
    base: str
    first_attempt: str  # the first Developer call, from the crew's events (UTC)
    note: str = ""

    @property
    def name(self) -> str:
        return f"{self.repo}-{self.card}"


CASES = {
    c.name: c
    for c in (
        Case(
            "sprint-metrics",
            662,
            "aa78bf2",
            "2026-10-17T19:27:26Z",
            "no pull request opened; main unchanged since 2026-10-16",
        ),
        Case("sprint-metrics", 596, "da6ff26", "2026-10-12T15:15:35Z", "PR 615's parent"),
        Case(
            "sprint-metrics",
            567,
            "2cf938a",
            "2026-10-11T07:32:00Z",
            "main before its first call; PR 584 came from a later re-delivery",
        ),
        Case(
            "crew-presentation",
            124,
            "af2c04f",
            "2026-10-17T05:48:15Z",
            "PR 142's parent; criterion 4's '0.5 days' kept as written",
        ),
        Case(
            "crew-presentation",
            83,
            "44d3c1d",
            "2026-10-15T21:04:42Z",
            "PR 93's parent; its failure was Google Fonts with no network",
        ),
    )
}


class UnknownCase(KeyError):
    """A case the benchmark doesn't have."""


def case(name: str) -> Case:
    if name not in CASES:
        raise UnknownCase(f"no case {name!r}; known: {', '.join(CASES)}")
    return CASES[name]


def story(c: Case) -> str:
    """The story as it stood at the first attempt, as kept in the repository."""
    path = STORIES / f"{c.name}.md"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: fetch it with `python -m benchmark.cases`")
    return path.read_text(encoding="utf-8")


def record(c: Case) -> str | None:
    """The project's record the case carries for its base, or None to use the base's own."""
    path = STORIES / f"{c.name}.project.yaml"
    return path.read_text(encoding="utf-8") if path.exists() else None


def as_it_stood(issue: dict, first_attempt: str) -> str:
    """The issue's body at the first attempt: the latest edit before it.

    With no edit before it, the earliest the history has, which is the body as opened.
    """
    edits = sorted(
        (e for e in issue["userContentEdits"]["nodes"] if e.get("diff") is not None),
        key=lambda e: e["editedAt"],
    )
    before = [e for e in edits if e["editedAt"] <= first_attempt]
    body = before[-1]["diff"] if before else (edits[0]["diff"] if edits else issue["body"])
    return f"# {issue['title']}\n\n{body}"


def fetch(c: Case) -> str:
    query = (
        f'{{repository(owner:"mqucifer",name:"{c.repo}"){{issue(number:{c.card}){{title body '
        "userContentEdits(first:50){nodes{editedAt diff}}}}}"
    )
    out = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True, check=True
    )
    return as_it_stood(json.loads(out.stdout)["data"]["repository"]["issue"], c.first_attempt)


def main() -> int:
    if sys.argv[1:] != ["--fetch"]:
        print("usage: python -m benchmark.cases --fetch", file=sys.stderr)
        return 2
    STORIES.mkdir(exist_ok=True)
    for c in CASES.values():
        path = STORIES / f"{c.name}.md"
        if path.exists():
            print(f"{c.name}: kept")
            continue
        path.write_text(fetch(c), encoding="utf-8")
        print(f"{c.name}: fetched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
