"""Each case's request, copied from LiteLLM's spend log to the records directory on the Mac.

    uv run role-fit extract

LiteLLM keeps every request and response, reasoning included, for 90 days
(`store_prompts_in_spend_logs` in infra's `compose/mac/litellm/config.yaml`). A
case's row is found by its `request_id`, which is the crew's `response_id`, and
read with one SELECT inside the database's container: its port is never
published, and nothing here writes to it.

The request is kept as production sent it, but for LiteLLM's own keys
(`metadata`, `litellm_trace_id`) and the stream settings, which the replay sets
itself. It's a prompt, so it stays on the Mac, readable by its owner only, in
`<records>/role_fit/requests/<id>.json`, with production's response beside it.
A case whose row is gone (past retention) is reported, never guessed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common.config import Settings
from role_fit.cases import Case

# infra's `compose/mac/litellm/compose.yaml` names it.
DATABASE = "litellm-temp-db"
# What LiteLLM adds to a request, and what the replay sets for itself.
DROPPED = {"metadata", "litellm_trace_id", "stream", "stream_options", "user"}
ID = re.compile(r"[0-9a-f]{32}")


class NotFound(LookupError):
    """The spend log no longer holds the case's request."""


def query(request_id: str) -> str:
    """The case's request and response from the spend log, as one JSON text."""
    if not ID.fullmatch(request_id):
        raise ValueError(f"not a request id: {request_id!r}")
    sql = (
        "select json_build_object('request', proxy_server_request, 'response', response) "
        f"from \"LiteLLM_SpendLogs\" where request_id = '{request_id}'"
    )
    found = subprocess.run(
        ["docker", "exec", DATABASE, "psql", "-U", "litellm_admin", "-d", "litellm", "-Atc", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return found.stdout.strip()


def requests_dir(settings: Settings) -> Path:
    return settings.records_dir / "role_fit" / "requests"


def path(settings: Settings, c: Case) -> Path:
    return requests_dir(settings) / f"{c.id}.json"


def request(raw: dict[str, Any]) -> dict[str, Any]:
    """The request as production sent it, without LiteLLM's own keys."""
    return {k: v for k, v in raw.items() if k not in DROPPED}


def extract(settings: Settings, c: Case, read: Callable[[str], str] = query) -> Path:
    """Copy one case's request out of the spend log, once; a copy already made is kept."""
    out = path(settings, c)
    if out.exists():
        return out
    text = read(c.id)
    if not text:
        raise NotFound(f"{c.id}: not in LiteLLM's spend log")
    found = json.loads(text)
    if not isinstance(found.get("request"), dict) or not found["request"].get("messages"):
        raise NotFound(f"{c.id}: the spend log holds no request body for it")
    kept = {"request": request(found["request"]), "production": found.get("response")}
    out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(kept, fh)
    return out


def load(settings: Settings, c: Case) -> dict[str, Any]:
    """A case's kept request and production response; NotFound before it's extracted."""
    try:
        return json.loads(path(settings, c).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotFound(f"{c.id}: not extracted yet (uv run role-fit extract)") from exc
