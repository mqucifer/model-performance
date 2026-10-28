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
# The v2 base's image (mqucifer/model-performance#40): the same CadQuery image, with
# OSMesa for `view` and the `lookup` and `docs` indexes (`image/Dockerfile.v2`).
IMAGE_V2 = "model-performance/cadquery:2.8.0-v2"
# Where its indexes are, inside it.
LOOKUP_INDEX = "/opt/cad-eval/lookup.json"
DOCS_INDEX = "/opt/cad-eval/docs.json"


# The harness's own commands in a container, never the model's: no inherited
# environment, a PATH of the image's system directories only, and absolute binaries.
# A `run` can plant `python` or `timeout` in /work/.crew-home/.local/bin, first on the
# sandbox's PATH (the race review of #41: the reap and the measure were forged); the
# image's own filesystem is read-only and the user isn't root, so these can't be.
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
PYTHON = "/usr/local/bin/python"
FIXED = ["/usr/bin/env", "-i", f"PATH={SYSTEM_PATH}", "HOME=/tmp", "LANG=C.UTF-8"]
TIMEOUT = "/usr/bin/timeout"


def fixed(command: list[str], timeout: int, grace: int) -> list[str]:
    """`command` as the harness runs it: `python` by its absolute path, under `env -i`
    and the image's own `timeout`."""
    first = PYTHON if command[0] == "python" else command[0]
    return [*FIXED, TIMEOUT, "-k", str(grace), str(timeout), first, *command[1:]]


def held(
    directory: Path, name: str, image: str = IMAGE, readonly: dict[Path, str] | None = None
) -> Any:
    """A held container over `directory`, not yet started. A part declares no services.

    crew's `Held`, with `run_fixed` for the harness's own commands beside its `exec`
    for the model's, and `readonly` host directories mounted read-only (the judging's
    container: the model's outputs, which nothing in it can change).
    """
    from crew_org.tools import container as crew  # noqa: PLC0415
    from crew_org.tools.sandbox import Sandbox, prepare_home  # noqa: PLC0415
    from crew_org.tools.services import Declared  # noqa: PLC0415

    class Fixed(crew.Held):
        def start(self) -> Any:
            if not readonly:
                return super().start()
            refused = self._refused("start")
            if refused:
                return refused
            prepare_home(self.worktree)
            argv = self.sandbox.command(
                self.worktree,
                ["sleep", str(self.lifetime)],
                network=False,
                held=self.name,
                labels=self._labels(),
                readonly=readonly,
            )
            done = crew._run(argv, "start", timeout=120)
            self.started = done.ok
            return done

        def run_fixed(self, command: list[str], timeout: int, stdin: str | None = None) -> Any:
            argv = [
                self.sandbox.engine,
                "exec",
                *(["-i"] if stdin is not None else []),
                "-w",
                "/work",
                self.name,
                *fixed(command, timeout, crew.GRACE),
            ]
            done = crew._said(
                crew._run(argv, " ".join(command), timeout + crew.GRACE + 30, stdin), timeout
            )
            if not done.ok and "Error response from daemon" in done.output and not self._running():
                self.lost = True
                return crew.Result(
                    done.command,
                    125,
                    f"the workspace container is gone: {done.output}",
                    done.seconds,
                )
            return done

    return Fixed(directory, name, sandbox=Sandbox(image=image), declared=Declared())


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
