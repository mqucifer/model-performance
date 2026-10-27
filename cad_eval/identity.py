"""What a run ran on, read rather than typed (mqucifer/model-performance#40, V4).

- **The harness:** this checkout's commit, and whether it has uncommitted changes. A
  dirty tree refuses to run, so every row names code that exists.
- **The texts:** one sha256 over the skill and reference files the session can read,
  so two runs with the same hash saw the same words.
- **The serving:** what production runs, from infra's own record of it
  (`inventory/services/sglang.yaml` at infra's main commit): the image's tag and
  digest, and the model. It's read at the batch's start and again as each run ends, so
  a change during the run shows. Nothing here probes SGLang: each call's response
  names the model that served it, and the session records that (`session.py`).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
INFRA = Path.home() / "Documents" / "git" / "infra"
SGLANG_RECORD = "inventory/services/sglang.yaml"


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


def serving(infra: Path = INFRA) -> dict[str, str | None]:
    """infra's record at its main commit, read from git's objects (nothing checked out
    or changed), with that commit; all none if infra can't be read."""
    try:
        commit = _git(infra, "rev-parse", "--short", "main")
        text = _git(infra, "show", f"main:{SGLANG_RECORD}")
    except (OSError, subprocess.CalledProcessError):
        return {"serving_infra_commit": None, **serving_from("")}
    return {"serving_infra_commit": commit, **serving_from(text)}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
