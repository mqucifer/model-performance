"""`view`'s pictures on real CadQuery, in the view image (skipped where it isn't built)."""

from __future__ import annotations

import base64
import contextlib
import os
import struct

import pytest

from cad_eval import container
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_VIEW) is None, reason=f"{container.IMAGE_VIEW} isn't built"
)
MAKE = """
import cadquery as cq
box = cq.Workplane("XY").box(40, 30, 20, centered=(True, True, False)).faces(">Z").shell(-2)
lid = cq.Workplane("XY").workplane(offset=20).box(40, 30, 2, centered=(True, True, False))
cq.exporters.export(box, "box.step")
cq.exporters.export(lid, "lid.step")
"""
BOARD = "mate = cq.Workplane('XY').workplane(offset=6).box(30, 20, 8, centered=(True, True, False))"


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("view")
    (directory / "make.py").write_text(MAKE)
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(
            directory, f"test-{directory.name}-{os.getpid()}", image=container.IMAGE_VIEW
        )
        assert held.start().ok
        try:
            t = PartTools(directory, held, arm="refs-measure-view", keepouts=[BOARD])
            assert t.call("run", '{"path": "make.py"}').outcome == "ok"
            yield t
        finally:
            held.stop()


@pytest.mark.parametrize("view", ["iso", "top", "front", "side", "exploded", "section x=0"])
def test_each_view_is_a_picture(tools: PartTools, view: str) -> None:
    found = tools.call("view", f'{{"files": "box.step lid.step", "view": "{view}"}}')
    assert found.outcome == "ok", found.reply
    png = base64.b64decode(found.image)
    # A PNG, 768 by 768, read off its own header (the host has no imaging library).
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (768, 768)
    # Not blank: the parts and the keep-out cover a good share of the picture.
    assert found.painted > 0.15
