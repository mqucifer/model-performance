"""The crew a run imports: the commit `pyproject.toml` pins, as installed."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, distribution


def commit() -> str:
    """The installed crew-org's commit, from its install record; "unknown" if there's none.

    A run records it beside its numbers, so a result always names the crew it ran.
    """
    try:
        raw = distribution("crew-org").read_text("direct_url.json")
    except PackageNotFoundError:
        return "unknown"
    if not raw:
        return "unknown"
    return str(json.loads(raw).get("vcs_info", {}).get("commit_id") or "unknown")
