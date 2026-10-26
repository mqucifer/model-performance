"""A run's records directory is new and its owner's only."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.config import load
from common.records import run_dir


def test_a_run_dir_is_private_and_never_reused(tmp_path: Path) -> None:
    settings = load(home=tmp_path)
    path = run_dir(settings, "benchmark", "case", "run")
    assert path.stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError):
        run_dir(settings, "benchmark", "case", "run")


def test_two_runs_of_a_case_in_the_same_second_each_get_their_own_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from common import records  # noqa: PLC0415

    settings = load(home=tmp_path)
    monkeypatch.setattr(records, "run_id", lambda now=None: "20261026T110009Z")
    first = records.new_run(settings, "benchmark", "case")
    second = records.new_run(settings, "benchmark", "case")
    third = records.new_run(settings, "benchmark", "case")
    assert [r for r, _ in (first, second, third)] == [
        "20261026T110009Z",
        "20261026T110009Z-2",
        "20261026T110009Z-3",
    ]
    assert all(path.is_dir() for _, path in (first, second, third))
    # Another case in the same second keeps the plain id.
    assert records.new_run(settings, "benchmark", "other")[0] == "20261026T110009Z"
