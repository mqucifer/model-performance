"""`measure`'s queries on a real part, in the evaluation's image (skipped without it)."""

from __future__ import annotations

import contextlib
import json
import os

import pytest

from cad_eval import container
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id() is None, reason=f"{container.IMAGE} isn't built"
)
MAKE = """
import cadquery as cq
a = (
    cq.Workplane("XY").box(30, 20, 6, centered=(True, True, False))
    .faces(">Z").workplane().pushPoints([(-8, 0)]).hole(4.5)
)
a = a.union(cq.Workplane("XY").workplane(offset=6).center(8, 0).circle(3).extrude(10))
cq.exporters.export(a, "part.step")
b = (
    cq.Workplane("XY").workplane(offset=6.3).box(30, 20, 2, centered=(True, True, False))
    .faces(">Z").workplane().center(8, 0).hole(6.6)
)
cq.exporters.export(b, "lid.step")
"""


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("measure")
    (directory / "make.py").write_text(MAKE)
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(directory, f"test-{directory.name}-{os.getpid()}")
        assert held.start().ok
        try:
            t = PartTools(directory, held, arm="base")
            t.plan_passed = True  # the plan gate is `test_plan.py`'s
            assert t.call("run", '{"path": "make.py"}').outcome == "ok"
            yield t
        finally:
            held.stop()


def ask(tools: PartTools, query: str) -> dict:
    found = tools.call("measure", json.dumps({"path": "part.step", "query": query}))
    assert found.outcome == "ok", found.reply
    return json.loads(found.reply)


def test_a_holes_diameter_and_axis(tools: PartTools) -> None:
    hole = ask(tools, "hole -8,0,3")["hole"]
    assert hole["diameter"] == pytest.approx(4.5) and abs(hole["axis"][2]) == 1


def test_the_distance_between_faces_by_selector_or_point(tools: PartTools) -> None:
    assert ask(tools, "distance >Z <Z")["gap_along_normal"] == pytest.approx(16)
    assert ask(tools, "distance <Z 8,0,16")["distance"] == pytest.approx(16)


def test_the_clearance_to_another_file_and_a_faces_position(tools: PartTools) -> None:
    assert ask(tools, "clearance lid.step")["clearance"] == {"interference": 0.0, "distance": 0.3}
    top = ask(tools, "position >Z")["faces"][0]
    assert top["centre"] == pytest.approx([8, 0, 16]) and top["normal"] == [0, 0, 1]


def test_a_query_it_cant_read_fails(tools: PartTools) -> None:
    assert tools.call("measure", '{"path": "part.step", "query": "spin >Z"}').why == "not_a_query"
