"""What else called the model while a run did, from LiteLLM's own log of every call.

The Spark serves one model to everyone: the crew's ticks, every builder, and anything
else through the proxy. So a run's times depend on what overlapped it, and
`concurrent_tick` sees only a `crew tick` process. This counts every call in
`LiteLLM_SpendLogs` whose start and end overlap the run's window, but the run's own,
told apart by request id. The builders share a key, so its alias can't. The proxy's
`request_id` is the response's `id`, which the session's `llm.finished` events keep as
`response_id`.

A SELECT through `docker exec` into the proxy's database, as the proxy's admin user:
only ids, times and aliases are read, never a prompt or an answer. A database that
can't be read gives None, and the row's `other_calls` is null, not 0.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

DATABASE = "litellm-temp-db"
QUERY = """select request_id, coalesce(metadata->>'user_api_key_alias', '?'), model_group
from "LiteLLM_SpendLogs" where "startTime" < '{until}' and "endTime" > '{since}'"""


def psql(sql: str) -> str:
    return subprocess.run(
        ["docker", "exec", DATABASE, "psql", "-U", "litellm_admin", "-d", "litellm", "-Atc", sql],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout


def own_calls(events: Path) -> set[str]:
    """The run's own request ids: each `llm.finished` event's `response_id`."""
    ids: set[str] = set()
    if not events.exists():
        return ids
    with events.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("kind") == "llm.finished":
                found = (event.get("detail") or {}).get("response_id")
                if found:
                    ids.add(str(found))
    return ids


def others(
    since: datetime, until: datetime, own: Iterable[str], read: Callable[[str], str] | None = None
) -> Counter[str] | None:
    """Calls that overlapped the window and aren't the run's, by `key alias/model group`;
    None if the log can't be read. Times are UTC, as the proxy writes them."""
    stamp = "%Y-%m-%d %H:%M:%S.%f"
    sql = QUERY.format(since=since.strftime(stamp), until=until.strftime(stamp))
    try:
        out = (read or psql)(sql)
    except (subprocess.SubprocessError, OSError):
        return None
    mine = set(own)
    found: Counter[str] = Counter()
    for line in out.splitlines():
        request, key, group = (line.split("|") + ["?", "?"])[:3]
        if request and request not in mine:
            found[f"{key}/{group}"] += 1
    return found


def keys(found: Counter[str]) -> str | None:
    """The other callers' key aliases, short enough for a row; None with none."""
    names = sorted({re.sub(r"[^A-Za-z0-9_.:@-]", "_", k.split("/", 1)[0]) for k in found})
    return "+".join(names)[:80] or None
