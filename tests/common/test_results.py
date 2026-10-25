"""A results row holds numbers, flags and short names, never text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.results import NotNumbers, append, problems

ROW = {
    "case": "sprint-metrics-662",
    "run": "20261025T010203Z",
    "at": "2026-10-25T01:02:03+00:00",
    "crew_commit": "099879fe31216b5c3b1b4fb7d8db0c00208d6496",
    "model_alias": "crew-code-think",
    "ending": "done",
    "calls": 42,
    "gate_green": True,
    "stop": None,
    "model_s": 812.4,
}


def test_a_row_of_numbers_is_appended(tmp_path: Path) -> None:
    path = append("benchmark", ROW, tmp_path)
    assert json.loads(path.read_text()) == {"suite": "benchmark", **ROW}


@pytest.mark.parametrize(
    ("extra", "why"),
    [
        ({"prompt": "x"}, "not a declared field"),
        ({"ending": "the model said it was done"}, "short names"),
        ({"case": "a" * 81}, "short names"),
        ({"calls": [1, 2]}, "short names"),
    ],
)
def test_text_is_refused(tmp_path: Path, extra: dict, why: str) -> None:
    with pytest.raises(NotNumbers, match=why):
        append("benchmark", {**ROW, **extra}, tmp_path)
    assert not (tmp_path / "benchmark.jsonl").exists()


def test_an_unknown_suite_is_refused() -> None:
    assert problems({"suite": "other"}) == ["suite must be one of ['benchmark', 'cad_eval', 'tuning']"]
