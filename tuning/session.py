"""One benchmark session of a concurrent run: `replay`, with each workspace capped lower.

    python -m tuning.session --memory 1536m -- CASE --sessions 6 --serving record --batch ID

The Sponsor caps each benchmark workspace at 1.5 GiB (mqucifer/model-performance#7),
so 6 to 8 fit in Docker Desktop's 12 GiB. crew at the pin caps its sandbox at 2g, in
the module constant `MEMORY` that both its sandbox and its services read, with no
public setting. It becomes one in mqucifer/crew#821's step 2 (workspace caps). Until
then, and until the pin moves to it, the constant is set here, in this process only,
before the replay starts; this module goes once crew has the setting.
"""

from __future__ import annotations

import re
import sys

MEMORY = re.compile(r"[1-9][0-9]*[mg]")


def cap(memory: str) -> None:
    """Every container crew starts in this process gets `memory`, swap included."""
    if not MEMORY.fullmatch(memory):
        raise ValueError(f"a memory cap such as 1536m, not {memory!r}")
    from crew_org.tools import container, sandbox  # noqa: PLC0415

    sandbox.MEMORY = memory
    container.MEMORY = memory


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3 or argv[0] != "--memory" or argv[2] != "--":
        print("usage: python -m tuning.session --memory CAP -- REPLAY_ARGS...", file=sys.stderr)
        return 2
    cap(argv[1])
    from benchmark import replay  # noqa: PLC0415

    return replay.main(argv[3:])


if __name__ == "__main__":
    sys.exit(main())
