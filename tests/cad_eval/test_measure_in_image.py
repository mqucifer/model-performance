"""`measure`'s queries on a real part, in the evaluation's image (skipped without it)."""

from __future__ import annotations

import contextlib
import json
import os

import pytest

from cad_eval import container
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
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
# V5's pin (press-fit-pin, 20261027T141934Z): chamfered at both ends.
pin = cq.Workplane("XY").circle(2.55).extrude(16).edges("%CIRCLE").chamfer(0.5)
cq.exporters.export(pin, "pin.step")
# Two solids of one part, 0.5 apart along X.
two = cq.Workplane("XY").box(2, 2, 2).union(cq.Workplane("XY").center(2.5, 0).box(2, 2, 2))
cq.exporters.export(two, "two.step")
"""


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("measure")
    (directory / "make.py").write_text(MAKE)
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        # The image the runs use (#40: the v2 image, not the CadQuery one under it).
        held = container.held(
            directory, f"test-{directory.name}-{os.getpid()}", image=container.IMAGE_V2
        )
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


def test_an_outer_diameter_is_measured_as_a_hole_is(tools: PartTools) -> None:
    """V5's review: `hole` on a plain pin said "no cylindrical face in the part"."""
    found = json.loads(
        tools.call("measure", '{"path": "pin.step", "query": "diameter 0,0,8"}').reply
    )
    assert found["diameter"]["diameter"] == 5.1 and found["diameter"]["kind"] == "outer"
    boss = json.loads(
        tools.call("measure", '{"path": "part.step", "query": "diameter 8,0,12"}').reply
    )
    assert (boss["diameter"]["diameter"], boss["diameter"]["kind"]) == (6.0, "outer")
    hole = json.loads(
        tools.call("measure", '{"path": "part.step", "query": "diameter -8,0,3"}').reply
    )
    assert (hole["diameter"]["diameter"], hole["diameter"]["kind"]) == (4.5, "hole")


def test_no_hole_names_the_cylinders_there_are(tools: PartTools) -> None:
    found = tools.call("measure", '{"path": "pin.step", "query": "hole 0,0,8"}')
    error = json.loads(found.reply)["error"]
    assert "no hole" in error and "Ø5.1" in error and "`diameter x,y,z`" in error
    assert "no cylindrical face" not in error


def test_a_section_clipped_to_a_span_reads_only_its_part(tools: PartTools) -> None:
    """A clevis's cheek, of the two a plane cuts (round 2 of #41's audit): the base here,
    30 mm along X, cut at Z = 3, and only its half at X >= 0."""
    whole = {"axis": "z", "at": 3}
    half = {**whole, "clip": {"axis": "x", "span": [0, 100]}}
    found = tools.measure_request({"path": "part.step", "sections": [whole, half]})["sections"]
    assert found[0]["bbox"][0] == [-15.0, 15.0]
    assert found[1]["bbox"][0] == [0.0, 15.0]


def test_a_gap_within_a_box_and_between_a_parts_own_solids(tools: PartTools) -> None:
    """Round 2 of #41's audit: one face pair's clearance, not only the closest of all."""
    lid = {"name": "lid", "path": "lid.step"}
    found = tools.measure_request(
        {
            "path": "part.step",
            "regions": [
                {"name": "top", "other": lid, "box": [[-15, -2], [-10, 10], [0, 10]]},
                {"name": "none", "other": lid, "box": [[100, 101], [0, 1], [0, 1]]},
            ],
        }
    )["regions"]
    assert abs(found["top"]["distance"] - 0.3) < 1e-3
    assert found["none"]["distance"] is None and "no material" in found["none"]["error"]
    own = tools.measure_request(
        {
            "path": "two.step",
            "regions": [{"name": "g", "other": "self", "box": [[-5, 5], [-5, 5], [-5, 5]]}],
        }
    )["regions"]
    assert abs(own["g"]["distance"] - 0.5) < 1e-3


def test_a_request_over_an_arguments_limit_is_measured(tools: PartTools) -> None:
    """Linux takes one argument of at most 128 KiB: the request goes on stdin (the
    operator, before the baseline). A key the measure doesn't read pads it past that."""
    request = {"path": "part.step", "probes": [[0, 0, 3], [0, 0, 50]], "pad": "x" * 200_000}
    assert tools.measure_request(request)["inside"] == [True, False]


def test_a_distance_says_between_which_faces_and_where(tools: PartTools) -> None:
    """V5 at 3706cd8: `distance >Z <Z` read 12.06 on a part 32 tall, and the model gave
    up on it. The reply names the two closest faces and their closest points, and
    every face a selector picked when it picked more than one."""
    found = ask(tools, "distance >Z <Z")
    assert found["distance"] == 16.0
    assert [p[2] for p in found["points"]] == [16.0, 0.0]
    assert found["between"][">Z"]["type"] == "PLANE" and found["between"][">Z"]["centre"][2] == 16
    assert found["between"]["<Z"]["centre"][2] == 0
    assert "closest distance" in found["measured"]
    # A selector naming several faces: each is listed, with the count.
    several = ask(tools, "distance %PLANE <Z")
    assert several["picked"]["%PLANE"]["count"] > 1
    assert several["distance"] == 0.0
