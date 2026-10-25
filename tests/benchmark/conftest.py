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
