"""A case's fetched inputs, from the benchmark's own captured copies, never a release.

mqucifer/model-performance#32. crew's package retention prunes old delivery-history
releases (ADR 0021 in mqucifer/crew): crew-presentation-124's archive went on
2026-10-26, and more go as days pass. So every case's fetched inputs were captured
once, by sha256, into the records directory on the Mac, which the nightly backup
archives (`records/inputs/`: `blobs/<sha256>` and `manifest.json`, which says where
each came from and why it's what the case saw).

Before a case's setup the replay:
- verifies each of the case's inputs against its hash, and refuses the case
  (`input_missing`, saying which and why) if one is missing or differs: never a
  fetch, never a stand-in;
- writes them into the worktree's `.package/`, as the repository's own setup would;
- and runs a setup of the benchmark's (`.benchmark/setup.py`, excluded from the
  worktree's git) that installs the locked dependencies through the repository's own
  `_sync_dependencies()`, and downloads nothing. Only the record's `setup:` line
  changes, and only for a case with inputs.

PyPI packages aren't captured: every case installs them under its lockfile's hashes,
and PyPI doesn't prune.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.config import Settings

# The repository's own setup command, and the one that replaces it for a case with inputs.
REPO_SETUP = "setup: python tools/setup.py"
SETUP = "setup: python .benchmark/setup.py"
SETUP_SCRIPT = '''"""The benchmark's setup (model-performance#32): the locked dependencies only.

The case's inputs (the delivery-history package and the design-system CSS) were
written into .package/ by the benchmark from its captured copies, checked by sha256.
Nothing is downloaded here.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("repo_setup", ROOT / "tools" / "setup.py")
repo_setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo_setup)
repo_setup._sync_dependencies()
package = ROOT / ".package"
if not package.is_dir() or not any(package.iterdir()):
    print(f"Missing: {package}, which the benchmark writes before setup", file=sys.stderr)
    sys.exit(1)
print("Setup complete: dependencies from uv.lock; inputs from the benchmark's captured copies")
'''


class InputMissing(Exception):
    """A case's input isn't in the captured copies, or isn't what was captured."""


@dataclass(frozen=True)
class Input:
    input: str  # delivery-history, design-system-css
    pin: str  # the tag or version the repository pins
    sha256: str
    path: Path


def manifest_path(settings: Settings) -> Path:
    return settings.records_dir / "inputs" / "manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def for_case(settings: Settings, name: str) -> tuple[str, list[Input]]:
    """The manifest's sha256 and the case's inputs, each checked against its hash.

    Raises `InputMissing`, saying which and why, if the manifest, the case's entry, a
    blob, or a blob's hash isn't as captured.
    """
    path = manifest_path(settings)
    if not path.is_file():
        raise InputMissing(f"no captured inputs: {path} is missing")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if name not in manifest.get("cases", {}):
        raise InputMissing(f"{name} isn't in {path}: its inputs were never captured")
    found = []
    for entry in manifest["cases"][name]:
        blob = path.parent / "blobs" / entry["sha256"]
        if not blob.is_file():
            raise InputMissing(f"{entry['input']} {entry['pin']}: no blob {blob.name}")
        actual = sha256(blob)
        if actual != entry["sha256"]:
            raise InputMissing(
                f"{entry['input']} {entry['pin']}: blob {blob.name} hashes to {actual}"
            )
        found.append(Input(entry["input"], entry["pin"], entry["sha256"], blob))
    return sha256(path), found


def place(root: Path, inputs: list[Input]) -> None:
    """Write the inputs into the worktree's `.package/` as the repository's setup would,
    and the benchmark's setup beside them, both kept out of the worktree's git."""
    package = root / ".package"
    package.mkdir(parents=True, exist_ok=True)
    for given in inputs:
        if given.input == "delivery-history":
            target = package / given.pin
            if target.is_dir():
                shutil.rmtree(target)
            with tarfile.open(given.path, "r:gz") as tar:
                tar.extractall(path=package, filter="data")
            if not (target / "delivery-history.json").is_file():
                raise InputMissing(f"{given.pin}: no delivery-history.json in its archive")
        elif given.input == "design-system-css":
            shutil.copyfile(given.path, package / f"design-system-{given.pin}.css")
        else:
            raise InputMissing(f"{given.input}: the benchmark doesn't know where it goes")
    script = root / ".benchmark" / "setup.py"
    script.parent.mkdir(exist_ok=True)
    script.write_text(SETUP_SCRIPT, encoding="utf-8")
    # Git's own answer for where this checkout's excludes live: for a linked worktree,
    # its shared git directory's, which is the one git reads.
    where = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    exclude = Path(where) if Path(where).is_absolute() else root / where
    exclude.parent.mkdir(parents=True, exist_ok=True)
    kept = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    for line in (".benchmark/", ".package/"):
        if line not in kept.splitlines():
            kept += ("" if kept.endswith("\n") or not kept else "\n") + line + "\n"
    exclude.write_text(kept, encoding="utf-8")


def setup_record(text: str, inputs: list[Input]) -> str:
    """The case's record with the benchmark's setup, for a case with inputs; else as is."""
    if not inputs:
        return text
    if REPO_SETUP not in text:
        raise InputMissing("the record's setup isn't `python tools/setup.py`: not replaced")
    return text.replace(REPO_SETUP, SETUP, 1)


def row_fields(manifest_sha: str, inputs: list[Input]) -> dict[str, str | None]:
    """What the row records: the manifest's sha256, and each input's."""
    by = {i.input: i.sha256 for i in inputs}
    return {
        "inputs_manifest": manifest_sha,
        "input_delivery_history": by.get("delivery-history"),
        "input_design_system_css": by.get("design-system-css"),
    }
