"""Fails when a tracked file could hold a prompt or an answer: the repository keeps numbers only.

Run records hold prompts and answers, so they stay on the Mac (ADR 0004 in
mqucifer/project-print, ADR 0010 in mqucifer/crew). Three checks over the
tracked files:

- each row of `results/*.jsonl` is a results row: declared fields of numbers,
  flags and short names only (`common/results.py`);
- no file is named as a run's records are, and no JSON Lines file sits outside
  `results/`;
- no data file holds a chat message's shape: a `role` of system, user,
  assistant or tool, or a `reasoning_content`.

Standard library only, so CI runs it without the project's dependencies.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.results import problems  # noqa: E402

# What a run writes to its records directory (benchmark/replay.py), and crew's own.
RECORD_NAMES = {
    "transcript.jsonl",
    "events.jsonl",
    "telemetry.jsonl",
    "start.md",
    "result.json",
    "diff.patch",
    "gate.json",
}
CHAT = re.compile(r'"role"\s*:\s*"(?:system|user|assistant|tool)"|"reasoning_content"')
# Code builds messages; data files would only hold them.
DATA = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".csv", ".log", ".patch"}


def findings(path: str, text: str) -> list[str]:
    found = []
    posix = PurePosixPath(path)
    if posix.name in RECORD_NAMES:
        found.append(f"{path}: named as a run's records are; they stay on the Mac")
    if posix.suffix == ".jsonl":
        if posix.parts[0] != "results" or len(posix.parts) != 2:
            found.append(f"{path}: JSON Lines outside results/")
        else:
            for number, line in enumerate(text.splitlines(), start=1):
                try:
                    row = json.loads(line)
                except ValueError:
                    found.append(f"{path}:{number}: not JSON")
                    continue
                found += [f"{path}:{number}: {p}" for p in problems(row)]
    if posix.suffix in DATA:
        for number, line in enumerate(text.splitlines(), start=1):
            if CHAT.search(line):
                found.append(f"{path}:{number}: a chat message's shape")
    return found


def main() -> int:
    files = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    failed = []
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        failed += findings(path, text)
    for line in failed:
        print(line)
    if failed:
        print("the repository keeps numbers only: prompts, answers and records stay on the Mac")
        return 1
    print(f"prompts: ok ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
