"""The escape as the second review of #41 made it: links made by a `run` in the
container, on the bind-mounted part's directory, then used through the host-side
tools. Every one is refused. In the v2 image (skipped where it isn't built)."""

from __future__ import annotations

import contextlib
import json
import os

import pytest

from cad_eval import container
from cad_eval import run as cad
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
)


def test_links_made_in_the_container_are_refused_on_the_host(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    secret = tmp_path_factory.mktemp("secret")
    (secret / "cases.py").write_text("ANSWER = 42\n")
    part = tmp_path_factory.mktemp("part")
    # The host path the link names: the container can name any path, and the host
    # resolves it.
    (part / "make.py").write_text(
        "import os\n"
        f"os.symlink({str(secret / 'cases.py')!r}, 'key.py')\n"
        f"os.symlink({str(secret)!r}, 'out')\n"
    )
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(part, f"escape-{os.getpid()}", image=container.IMAGE_V2)
        assert held.start().ok
        try:
            tools = PartTools(part, held, arm="base")
            tools.plan_passed = True
            assert tools.call("run", '{"path": "make.py"}').outcome == "ok"
            assert (part / "key.py").is_symlink()
            read = tools.call("read", json.dumps({"path": "key.py"}))
            assert read.why == "outside" and "ANSWER" not in read.reply
            write = tools.call("write", json.dumps({"path": "out/cases.py", "content": "x\n"}))
            assert write.why == "outside"
            assert (secret / "cases.py").read_text() == "ANSWER = 42\n"
            records = tmp_path_factory.mktemp("records")
            cad.keep(part, records)
            assert not (records / "files" / "key.py").exists()
        finally:
            held.stop()
