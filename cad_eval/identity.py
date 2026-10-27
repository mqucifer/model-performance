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
    return {
        "serving_image": image.group(1) if image else None,
        "serving_digest": digest.group(1) if digest else None,
        "serving_model": model.group(1) if model else None,
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


def changed(start: dict[str, Any], end: dict[str, Any]) -> bool:
    """Whether production's serving differs, by what's recorded: never the commit alone."""
    return any(start.get(k) != end.get(k) for k in RECORDED)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
