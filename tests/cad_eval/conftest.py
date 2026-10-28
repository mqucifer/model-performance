"""A clean harness for every test that runs the CLI: a test's own checkout is often
mid-change, and `cad-eval` refuses to run on uncommitted changes (`identity.py`)."""

from __future__ import annotations

import pytest

from cad_eval import identity


@pytest.fixture(autouse=True)
def clean_harness(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("real_harness") is None:
        monkeypatch.setattr(identity, "harness", lambda: {"commit": "0" * 40, "dirty": False})
