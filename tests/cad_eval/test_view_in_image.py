"""`view`'s pictures on real CadQuery, in the v2 image (skipped where it isn't built)."""

from __future__ import annotations

import base64
import contextlib
import os
import struct

import pytest

from cad_eval import container
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
)
# The model's own files: a box, its lid, and a board it modelled to see it inside.
MAKE = """
import cadquery as cq
box = cq.Workplane("XY").box(40, 30, 20, centered=(True, True, False)).faces(">Z").shell(-2)
lid = cq.Workplane("XY").workplane(offset=20).box(40, 30, 2, centered=(True, True, False))
board = cq.Workplane("XY").workplane(offset=6).box(30, 20, 8, centered=(True, True, False))
cq.exporters.export(box, "box.step")
cq.exporters.export(lid, "lid.step")
cq.exporters.export(board, "board.step")
"""


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("view")
    (directory / "make.py").write_text(MAKE)
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        name = f"test-{directory.name}-{os.getpid()}"
        held = container.held(directory, name, image=container.IMAGE_V2)
        assert held.start().ok
        try:
            t = PartTools(directory, held, ["box.step", "lid.step"], arm="base")
            t.plan_passed = True
            assert t.call("run", '{"path": "make.py"}').outcome == "ok"
            yield t
        finally:
            held.stop()


@pytest.mark.parametrize("view", ["iso", "top", "front", "side", "exploded", "section x=0"])
def test_each_view_is_a_picture(tools: PartTools, view: str) -> None:
    args = f'{{"files": "box.step lid.step", "view": "{view}", "keepouts": "board.step"}}'
    found = tools.call("view", args)
    assert found.outcome == "ok", found.reply
    png = base64.b64decode(found.image)
    # A PNG, 768 by 768, read off its own header (the host has no imaging library).
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (768, 768)
    # Not blank: the parts and the keep-out cover a good share of the picture.
    assert found.painted > 0.15
    assert "your keep-outs (board.step)" in found.reply


def test_a_keep_out_that_isnt_the_models_file_is_refused(tools: PartTools) -> None:
    args = '{"files": "box.step", "view": "iso", "keepouts": "pi5.step"}'
    assert tools.call("view", args).why == "no_file"
