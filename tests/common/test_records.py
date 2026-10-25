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
