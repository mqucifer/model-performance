"""The cases and the story text each run reads, offline."""

from __future__ import annotations

import pytest

from benchmark.cases import CASES, UnknownCase, as_it_stood, case, story


def test_every_case_has_its_story_kept() -> None:
    for c in CASES.values():
        assert story(c).startswith("# ")


def test_an_unknown_case_names_the_known_ones() -> None:
    with pytest.raises(UnknownCase, match="sprint-metrics-662"):
        case("nope-1")


def issue(*edits: tuple[str, str]) -> dict:
    return {
        "title": "T",
        "body": "now",
        "userContentEdits": {"nodes": [{"editedAt": at, "diff": d} for at, d in edits]},
    }


def test_the_story_is_the_latest_edit_before_the_first_attempt() -> None:
    found = issue(("2026-10-01T00:00:00Z", "opened"), ("2026-10-03T00:00:00Z", "edited"))
    assert as_it_stood(found, "2026-10-02T00:00:00Z") == "# T\n\nopened"
    assert as_it_stood(found, "2026-10-04T00:00:00Z") == "# T\n\nedited"


def test_with_no_edit_history_the_story_is_the_body() -> None:
    assert as_it_stood(issue(), "2026-10-02T00:00:00Z") == "# T\n\nnow"
