"""What a run ran on, read rather than typed (mqucifer/model-performance#40, V4).

- **The harness:** this checkout's commit, and whether it has uncommitted changes. A
  dirty tree refuses to run, so every row names code that exists.
- **The texts:** one sha256 over the skill and reference files the session can read,
  so two runs with the same hash saw the same words.
- **The serving:** what production runs, from infra's own record of it
  (`inventory/services/sglang.yaml`), and the route LiteLLM takes for the alias
  (`compose/mac/litellm/config.yaml`), both fetched from mqucifer/infra's main on
  GitHub, never a local clone that may be stale. It's read at the batch's start and
  again as each run ends; only the image, digest, model and route count as a change,
  never infra's commit alone. Nothing here probes SGLang: each call's response headers
  name the deployment that served it, and the session records them (`session.py`).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
INFRA_REPO = "mqucifer/infra"
SGLANG_RECORD = "inventory/services/sglang.yaml"
LITELLM_CONFIG = "compose/mac/litellm/config.yaml"
# What counts as a change of serving: never infra's commit alone.
RECORDED = ("serving_image", "serving_digest", "serving_model", "serving_route")


def harness(root: Path = ROOT) -> dict[str, Any]:
    """This checkout's commit, and whether its tracked files differ from it.

    Untracked files don't count: results rows are appended while a batch runs, and the
    run's records live outside the repository.
    """
    commit = _git(root, "rev-parse", "HEAD")
    changed = _git(root, "status", "--porcelain", "--untracked-files=no")
    dirty = any(line[3:] != "results/cad_eval.jsonl" for line in changed.splitlines())
    return {"commit": commit, "dirty": dirty}


def texts_sha(paths: Iterable[Path]) -> str:
    """One sha256 over files, each by its name and bytes, in the order given."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def serving_from(text: str) -> dict[str, str | None]:
    """The production serving infra's record states: its image, digest and model.

    The record is prose in YAML; each value is taken only where it's stated in the
    words infra uses ("image <tag>, pinned by digest <digest>", "the model, <name>").
    infra abbreviates a digest with "…"; a row's names are ASCII, so it's kept as "...".
    """
    text = text.replace("…", "...")
    image = re.search(r"\bimage (\S+?),", text)
    digest = re.search(r"pinned by digest (sha256:\S+?),", text)
    model = re.search(r"the model, (\S+)", text)
    port = re.search(r"\bapi: (\d+)", text)
    reached = re.search(r"^reached_by: (\w+)", text, re.M)
    return {
        "serving_image": image.group(1) if image else None,
        "serving_digest": digest.group(1) if digest else None,
        "serving_model": model.group(1) if model else None,
        "serving_port": port.group(1) if port else None,
        # The name of the address SGLang is reached by, never the address itself.
        "serving_reached_by": reached.group(1) if reached else None,
    }


def route_from(config: str, alias: str) -> str | None:
    """The model LiteLLM's config sends `alias` to, its provider prefix off: what
    SGLang serves it as."""
    block = re.search(
        rf"model_name: {re.escape(alias)}\s*\n(.*?)(?=\n  - model_name:|\Z)", config, re.S
    )
    found = re.search(r"\bmodel: (?:openai/)?(\S+)", block.group(1)) if block else None
    return found.group(1) if found else None


def gh(path: str) -> str:
    """A file or commit of infra's main, from GitHub (`gh api`)."""
    args = ["gh", "api", f"repos/{INFRA_REPO}/{path}"]
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=60).stdout


def serving(alias: str = "crew-code-think", fetch: Any = gh) -> dict[str, Any]:
    """infra's record of production's serving and the alias's route, at infra's main,
    fetched; whether the route names the container infra records; all none if it
    can't be fetched."""
    import base64  # noqa: PLC0415
    import json  # noqa: PLC0415

    try:
        commit = json.loads(fetch("commits/main"))["sha"][:7]

        def read(path: str) -> str:
            raw = json.loads(fetch(f"contents/{path}?ref={commit}"))["content"]
            return base64.b64decode(raw).decode()

        record, config = read(SGLANG_RECORD), read(LITELLM_CONFIG)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return {"serving_infra_commit": None, **serving_from(""), "serving_route": None}
    route = route_from(config, alias)
    container = re.search(r"\bcontainer (\S+?),", record)
    return {
        "serving_infra_commit": commit,
        **serving_from(record),
        "serving_route": route,
        "serving_route_matches": bool(route and container and route == container.group(1)),
    }


# What a call's comparison can find: a difference from infra's record, or nothing to
# compare with, which is never a match (the final review of #41).
MISMATCHES = ("model_group", "api_port", "api_host")
UNVERIFIED = (
    "unverified",
    "no_model_group",
    "no_api_base",
    "no_record_port",
    "no_record_host",
    "unresolved_host",
)
HOSTS_ENV = Path.home() / ".config" / "infra" / "hosts.env"


def ssh_hostname(alias: str, run: Any = subprocess.run) -> str | None:
    """The host an SSH alias names, from the local SSH config (`ssh -G`: nothing is
    connected to), or None when it names none of its own."""
    try:
        found = run(["ssh", "-G", alias], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in found.stdout.splitlines():
        if line.startswith("hostname "):
            name = line.split(None, 1)[1].strip()
            return name if name and name != alias else None
    return None


def reached_host(
    record: dict[str, Any],
    env: Path = HOSTS_ENV,
    resolve: Any = None,
    alias: Any = ssh_hostname,
) -> str | None:
    """The host SGLang is reached at, by the variable infra's record names
    (`reached_by: SPARK_ADDR`), from the environment or infra's local hosts file. Its
    value is an SSH alias on the Mac, which no DNS knows: one that doesn't resolve is
    the host its SSH config names. Kept in memory only: no row or record holds an
    address."""
    import os  # noqa: PLC0415

    resolve = resolve or addresses
    name = record.get("serving_reached_by")
    if not name:
        return None
    value = os.environ.get(name)
    if not value:
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                key, _, found = line.partition("=")
                if key.strip() == name and found.strip():
                    value = found.strip().strip('"').strip("'")
        except OSError:
            return None
    if not value:
        return None
    if resolve(value):
        return value
    return alias(value) or value


def addresses(host: str) -> frozenset[str]:
    """What a host name resolves to, or nothing: never raised."""
    import socket  # noqa: PLC0415

    try:
        return frozenset(a[4][0] for a in socket.getaddrinfo(host, None))
    except (OSError, UnicodeError):
        return frozenset()


_RESOLVED: dict[str, frozenset[str]] = {}


def same_host(served: str, expected: str, resolve: Any = addresses) -> bool | None:
    """Whether two hosts are one: the same name, or names whose addresses meet (LiteLLM's
    base is configured by one form, infra's record by another: the race review of #41).
    None when neither is the other and either can't be resolved."""
    if served.lower() == expected.lower():
        return True
    found = []
    for name in (served, expected):
        if name not in _RESOLVED or resolve is not addresses:
            _RESOLVED[name] = resolve(name)
        found.append(_RESOLVED[name])
    if not found[0] or not found[1]:
        return None
    return bool(found[0] & found[1])


def logged(headers: dict[str, str], differs: list[str]) -> dict[str, str]:
    """A call's served headers as its event keeps them: the api base's address replaced
    by whether it matched infra's record (`matched`, `mismatched`, or `unverified`)."""
    kept = {k: v for k, v in headers.items() if k != "x-litellm-model-api-base"}
    if "x-litellm-model-api-base" in headers:
        if {"api_host", "api_port"} & set(differs):
            kept["x-litellm-model-api-base"] = "mismatched"
        elif {"no_record_port", "no_record_host", "unresolved_host"} & set(differs):
            kept["x-litellm-model-api-base"] = "unverified"
        else:
            kept["x-litellm-model-api-base"] = "matched"
    return kept


def mismatch(
    headers: dict[str, str],
    alias: str,
    record: dict[str, Any],
    host: str | None = None,
    resolve: Any = addresses,
) -> list[str]:
    """How a call's serving, as LiteLLM's headers say it, differs from infra's record:
    the model group isn't the alias asked for, or the api base isn't at the host and
    port infra records for SGLang (`MISMATCHES`). What can't be compared is said, never
    taken for a match (`UNVERIFIED`): no headers, only one of the two, or no port or
    host on record (a failed fetch, or a record that doesn't say).

    LiteLLM's deployment id is a hash of its parameters, not compared (the operator:
    fragile, version-coupled). A model swapped under the same served name wouldn't show
    here: nothing probes SGLang, by the rules.
    """
    from urllib.parse import urlparse  # noqa: PLC0415

    group = headers.get("x-litellm-model-group")
    base = headers.get("x-litellm-model-api-base")
    if not group and not base:
        return ["unverified"]
    found = []
    if not group:
        found.append("no_model_group")
    elif group != alias:
        found.append("model_group")
    if not base:
        found.append("no_api_base")
        return found
    parsed = urlparse(base)
    port = record.get("serving_port")
    if not port:
        found.append("no_record_port")
    elif parsed.port != int(port):
        found.append("api_port")
    if not host:
        found.append("no_record_host")
    else:
        same = same_host(parsed.hostname or "", host, resolve)
        if same is None:
            found.append("unresolved_host")
        elif not same:
            found.append("api_host")
    return found


def changed(start: dict[str, Any], end: dict[str, Any]) -> bool:
    """Whether production's serving differs, by what's recorded: never the commit alone."""
    return any(start.get(k) != end.get(k) for k in RECORDED)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
