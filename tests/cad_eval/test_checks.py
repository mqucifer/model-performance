from __future__ import annotations

import pytest

from cad_eval import checks
from cad_eval.parts import FIRST, PARTS, UnknownPart, part


def measured(name: str, **override: object) -> dict:
    p = PARTS[name]
    found = {
        "valid": True,
        "solids": p.solids,
        "bbox": [list(axis) for axis in p.bbox],
        "volume": p.volume,
        "inside": [True] * len(p.inside) + [False] * len(p.outside),
        "mesh": {"watertight": True, "winding_consistent": True, "is_volume": True},
        "interference": 0.0 if p.mate else None,
    }
    return {**found, **override}


@pytest.mark.parametrize("name", list(PARTS))
def test_a_part_measured_as_its_spec_passes(name: str) -> None:
    found = checks.dimensions(PARTS[name], measured(name))
    assert [c.name for c in found if not c.ok] == []
    assert checks.closed(measured(name)) and checks.valid(measured(name))


def test_a_dimension_out_of_tolerance_fails_by_name() -> None:
    m = measured("spacer", bbox=[[-6, 6], [-6, 6], [0, 10.2]], volume=950.0)
    assert [c.name for c in checks.dimensions(PARTS["spacer"], m) if not c.ok] == [
        "bbox.z.max",
        "volume",
    ]


def test_a_probe_on_the_wrong_side_fails_by_its_feature() -> None:
    p = PARTS["l-bracket"]
    answers = [True] * len(p.inside) + [False] * len(p.outside)
    answers[list(p.inside).index("fillet")] = False
    m = measured("l-bracket", inside=answers)
    assert [c.name for c in checks.dimensions(p, m) if not c.ok] == ["in.fillet"]


def test_a_fit_that_overlaps_its_mate_fails() -> None:
    m = measured("box-lid", interference=3.2)
    assert [c.name for c in checks.dimensions(PARTS["box-lid"], m) if not c.ok] == ["interference"]


def test_a_measure_that_failed_fails_everything() -> None:
    found = checks.dimensions(PARTS["spacer"], {"error": "it doesn't load"})
    assert [(c.name, c.ok) for c in found] == [("measured", False)]
    assert not checks.valid({"error": "x"}) and not checks.closed({"error": "x"})


def test_an_open_mesh_isnt_closed() -> None:
    assert not checks.closed(measured("spacer", mesh={"watertight": False}))


def test_every_part_has_its_spec_and_the_first_run_one_per_tier() -> None:
    assert sorted(PARTS[n].tier for n in FIRST) == [1, 2, 3, 4, 5]
    for p in PARTS.values():
        assert p.spec().startswith("# ")
    with pytest.raises(UnknownPart):
        part("gear")
