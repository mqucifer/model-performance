"""The container a part's session works in: crew's own held workspace, with CadQuery's image.

crew's `Held` and `Sandbox` at the pinned commit, unchanged: no network, a read-only
image, the invoking user, capped memory, processes and CPUs, and the part's directory
as `/work`, the only thing written. The image is `cad_eval/image`'s, built on the Mac.
Generated code runs only here, never on the host (CLAUDE.md in mqucifer/project-print).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

IMAGE = "model-performance/cadquery:2.8.0"
# The same image and CadQuery, plus OSMesa so VTK renders offscreen: the `view` tool's
# arms run in it (mqucifer/model-performance#29). Only the rendering library differs.
IMAGE_VIEW = "model-performance/cadquery:2.8.0-osmesa"


def held(directory: Path, name: str, image: str = IMAGE) -> Any:
    """A held container over `directory`, not yet started. A part declares no services."""
    from crew_org.tools.container import Held  # noqa: PLC0415
    from crew_org.tools.sandbox import Sandbox  # noqa: PLC0415
    from crew_org.tools.services import Declared  # noqa: PLC0415

    return Held(directory, name, sandbox=Sandbox(image=image), declared=Declared())


def image_id(image: str = IMAGE, engine: str = "docker") -> str | None:
    """The built image's id, or None when it isn't built: a run refuses without it."""
    try:
        found = subprocess.run(
            [engine, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return found.stdout.strip() or None if found.returncode == 0 else None
