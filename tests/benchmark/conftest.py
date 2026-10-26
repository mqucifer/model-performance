from __future__ import annotations

import subprocess

import pytest

from common import spend


@pytest.fixture(autouse=True)
def no_spend_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads the proxy's real database: an unreadable log, as without Docker."""

    def unreadable(sql: str) -> str:
        raise subprocess.CalledProcessError(1, ["docker"])

    monkeypatch.setattr(spend, "psql", unreadable)


@pytest.fixture(autouse=True)
def captured_inputs(tmp_path: pytest.TempPathFactory) -> None:
    """Each test's records hold a manifest of captured inputs (`benchmark/inputs.py`): none
    for the sprint-metrics cases, which fetch nothing, as the real one has."""
    import json  # noqa: PLC0415

    from common.config import load  # noqa: PLC0415

    path = load(home=tmp_path).records_dir / "inputs" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = {f"sprint-metrics-{n}": [] for n in (567, 596, 662)}
    path.write_text(json.dumps({"blobs": {}, "cases": cases}), encoding="utf-8")


# The replay tests' clone, for every test module here.
from tests.benchmark.test_replay import repo  # noqa: E402, F401
