"""The harder cases' checks on made-up measures, whose a failure is, and a case end to end
with a scripted model and a fake container."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cad_eval import cases, checks
from cad_eval import run as cad
from cad_eval.cases import CASES, Gap, Holes, Load, Member, Vents, line, ring
from cad_eval.parts import PARTS
from cad_eval.session import SYSTEM, system_for
from common import results
from tests.cad_eval.test_run import Run, answer, call

HERE = Path(__file__).parent


def measured(m: Member, **override: Any) -> dict[str, Any]:
    """What a member made exactly to its spec would measure."""
    box = m.bbox or m.within
    inside = [True] * len(m.inside) + [False] * len(m.outside)
    for sample in m.samples:
        inside += [True] * len(sample.points)
    found: dict[str, Any] = {
        "valid": True,
        "solids": m.solids,
        "bbox": [list(axis) for axis in box],
        "volume": m.volume or (m.volume_range[0] if m.volume_range else 1.0),
        "inside": inside,
        "mesh": {"watertight": True, "winding_consistent": True, "is_volume": True},
    }
    if m.cylinders:
        found["cylinders"] = [
            {
                "radius": sum(c.radius) / 2,
                "axis": [1.0 if a == c.axis else 0.0 for a in "xyz"],
                "origin": list(c.through),
                "hole": c.kind == "hole",
            }
            for c in m.cylinders
        ]
    return {**found, **override}


def test_there_are_21_cases_of_three_kinds_each_with_its_spec_and_solutions() -> None:
    # Twenty, and the Sponsor's Raspberry Pi 5 case.
    assert len(CASES) == 21
    assert {c.kind for c in CASES.values()} == {"tight", "assembly", "worded"}
    assert not set(CASES) & set(PARTS)
    for case in CASES.values():
        assert case.spec().startswith("# ")
        assert (HERE / "reference" / f"{case.name}.py").is_file()
        assert (HERE / "wrong" / f"{case.name}.py").is_file()
        names = [m.name for m in case.members]
        assert len(set(names)) == len(names)
        for m in case.members:
            for gap in m.gaps:
                assert gap.other in names or gap.other in case.mates, (case.name, gap.other)
            assert m.bbox or m.within, (case.name, m.name)
    assert {CASES[n].kind for n in cases.FIRST} == {"tight", "assembly", "worded"}
    assert len(cases.FIRST) == 5 and "pi5-nvme-case" in cases.FIRST


def test_assemblies_have_two_to_five_members_and_the_others_one() -> None:
    for case in CASES.values():
        if case.kind == "assembly" or case.name == "pi5-nvme-case":
            assert 2 <= len(case.members) <= 5
            assert case.outputs() != ["part.step"]
        else:
            assert case.outputs() == ["part.step"]


@pytest.mark.parametrize("name", list(CASES))
def test_each_measure_request_fits_on_the_command_line(name: str) -> None:
    # Linux takes one argument of at most 128 KiB.
    for request in cad.requests(CASES[name]).values():
        assert len(json.dumps(request)) < 120_000


def test_a_request_asks_only_for_what_the_members_checks_need() -> None:
    clevis = cad.requests(CASES["pin-clevis"])
    assert clevis["pin"]["against"] == [
        {"name": "clevis", "path": "clevis.step"},
        {"name": "tongue", "path": "tongue.step"},
    ]
    assert "against" not in clevis["clevis"] and "section" not in clevis["clevis"]
    pin = cad.requests(CASES["press-fit-pin"])["part"]
    assert pin["against"] == [{"name": "block", "source": cases.BLOCK}]
    bracket = cad.requests(CASES["shelf-bracket"])["part"]
    assert bracket["section"] == {"axis": "x", "at": 20} and bracket["cylinders"] is True
    assert cad.requests(CASES["print-in-place-hinge"])["part"]["self"] is True


def test_a_press_fit_must_overlap_and_a_clearance_fit_must_not() -> None:
    press = Member("p", bbox=((0, 1),) * 3, gaps=(Gap("block", interference=(5.9, 9.2)),))
    loose = measured(press, against={"block": {"interference": 0.0, "distance": 0.0}})
    assert [c.name for c in checks.member(press, loose) if not c.ok] == ["gap.block.interference"]
    clear = Member("c", bbox=((0, 1),) * 3, gaps=(Gap("rail", distance=(0.15, 0.25)),))
    tight = measured(clear, against={"rail": {"interference": 0.0, "distance": 0.05}})
    assert [c.name for c in checks.member(clear, tight) if not c.ok] == ["gap.rail.distance"]
    gone = measured(clear, against={"rail": {"error": "it doesn't load"}})
    assert [c.name for c in checks.member(clear, gone) if not c.ok] == ["gap.rail"]


def test_samples_count_their_share_changes_and_gaps() -> None:
    teeth = ring("pitch", (0, 0, 0), 15, n=8, share=(0.4, 0.6), changes=(4, 4))
    found = checks.sampled(teeth, [True, True, False, False, True, True, False, False])
    assert [(c.name, c.ok) for c in found] == [("share.pitch", True), ("changes.pitch", True)]
    # Round a ring the last point meets the first.
    assert checks.sampled(teeth, [True] * 4 + [False] * 4)[1].found == 2
    comb = line("cables", (0, 0, 0), (0, 10, 0), n=11, gaps=(1.5, 2.5))
    assert comb.spacing == 1.0
    inside = [False, True, False, True, True, False, False, True, False, False, False]
    assert checks.gap_widths(inside, 1.0) == [2.0, 3.0]
    # Its share's window is 0 to 1, so no share check: only its gaps (#40 V2).
    assert [c.name for c in checks.sampled(comb, inside)] == ["gaps.cables"]
    assert not checks.sampled(comb, inside)[0].ok


def test_a_hole_cut_in_halves_counts_once() -> None:
    half = {"radius": 2.25, "axis": [1.0, 0, 0], "origin": [0, 8, -25], "hole": True}
    other = {"radius": 2.25, "axis": [-1.0, 0, 0], "origin": [5, -8, -55], "hole": True}
    boss = {"radius": 2.25, "axis": [1.0, 0, 0], "origin": [0, 0, 0], "hole": False}
    wide = {"radius": 4.0, "axis": [1.0, 0, 0], "origin": [0, 0, 9], "hole": True}
    screws = Holes("screws", "x", (2.1, 2.6), 2)
    assert (
        checks.holes_found(screws, [half, dict(half, origin=[3, 8, -25]), other, boss, wide]) == 2
    )


def test_the_load_check_is_the_bending_stress_at_its_section() -> None:
    # A 10 by 4 mm section (Y by Z) at X = 5: I = 10·4³/12 about Y, c = 2.
    section = {
        "area": 40.0,
        "centroid": [5.0, 0.0, 0.0],
        "moments": [[386.67, 0, 0], [0, 53.333, 0], [0, 0, 333.33]],
        "bbox": [[5, 5], [-5, 5], [-2, 2]],
    }
    spec = Load("shelf", "x", 5, force_n=5, arm_mm=50)
    assert checks.stress(spec, section) == pytest.approx(5 * 50 * 2 / 53.333, rel=1e-3)
    assert checks.load(spec, section).ok
    # Without an arm, the load hangs at the far end: 100 mm out, 95 from the section.
    far = Load("bag", "x", 5, force_n=10)
    box = [[0, 100], [-5, 5], [-2, 2]]
    assert checks.stress(far, section, box) == pytest.approx(10 * 95 * 2 / 53.333, rel=1e-3)
    assert not checks.load(Load("bag", "x", 5, force_n=60), section, box).ok
    assert not checks.load(spec, {"area": 0.0}).ok
    assert "simplified" in checks.load(spec, section).expected


def test_vents_are_the_open_lines_on_their_grid() -> None:
    vents = Vents("top", ((0, 9), (0, 3)), area=20.0)
    assert vents.points() == [(x, y) for x in (0, 3, 6, 9) for y in (0, 3)]
    m = Member("lid", bbox=((0, 1),) * 3, vents=vents)
    three_open = [True] * 5 + [False] * 3
    assert [c.found for c in checks.member(m, measured(m, rays=three_open))][-1] == 27.0
    assert checks.member(m, measured(m, rays=three_open))[-1].ok
    shut = checks.member(m, measured(m, rays=[True] * 8))[-1]
    assert (shut.name, shut.ok, shut.found) == ("vents.top", False, 0.0)
    assert not checks.member(m, measured(m, rays=[False] * 3))[-1].ok


def test_the_pi_case_checks_only_what_the_drawings_publish() -> None:
    case = CASES["pi5-nvme-case"]
    assert case.outputs() == ["base.step", "lid.step"]
    base, lid = case.members
    names = {s.name for s in base.samples}
    assert {"usb_c", "hdmi_0", "hdmi_1", "ethernet", "usb_29", "usb_47", "flex_cable"} <= names
    assert sum(n.startswith("boss_") for n in names) == 4
    assert lid.vents is not None and base.vents is None
    assert {g.other for g in lid.gaps} == {"pi5", "nvme_base", "base"}
    assert "microsd" not in " ".join(names).lower()


@pytest.mark.parametrize(
    ("row", "measured", "troubles", "fault"),
    [
        (
            {
                "ending": "done",
                "stop": None,
                "compiles": True,
                "closed_mesh": True,
                "within_tolerance": True,
            },
            {},
            {},
            None,
        ),
        (
            {
                "ending": "done",
                "stop": None,
                "compiles": True,
                "closed_mesh": True,
                "within_tolerance": False,
            },
            {"part": {}},
            {},
            "model",
        ),
        (
            {
                "ending": "done",
                "stop": None,
                "compiles": False,
                "closed_mesh": False,
                "within_tolerance": False,
            },
            {"part": {"error": "no part.step after exit 1"}},
            {},
            "model",
        ),
        (
            {
                "ending": "done",
                "stop": None,
                "compiles": True,
                "closed_mesh": True,
                "within_tolerance": False,
            },
            {"part": {"error": "the measure didn't finish (exit 137)"}},
            {},
            "tool",
        ),
        ({"ending": "blocked", "stop": "said"}, {}, {}, "model"),
        ({"ending": "blocked", "stop": "no_tool_call"}, {}, {"measure_unfinished": 2}, "tool"),
        ({"ending": "interrupted", "stop": "call_cap"}, {}, {}, "budget"),
        ({"ending": "blocked", "stop": "backstop"}, {}, {}, "budget"),
        ({"ending": "interrupted", "stop": "call_failed"}, {}, {}, "infra"),
        ({"ending": "refused", "stop": "no_image"}, {}, {}, "infra"),
        ({"ending": "crashed", "stop": "KeyError"}, {}, {}, "tool"),
    ],
)
def test_a_failure_is_the_models_a_tools_the_infrastructures_or_the_budgets(
    row: dict[str, Any], measured: dict[str, Any], troubles: dict[str, int], fault: str | None
) -> None:
    assert cad.fault(row, measured, troubles) == fault


SCRIPT = "import cadquery as cq\n"
DONE = [
    answer(call("write", {"path": "make.py", "content": SCRIPT})),
    answer(call("run", {"path": "make.py"})),
    answer(call("done", {"script": "make.py"})),
]


def go(r: Run, name: str, **kw: Any) -> dict[str, Any]:
    case = CASES[name]
    r.workspace.writes = {o: "step" for o in case.outputs()}

    def held(directory: Path, _: str) -> Any:
        r.workspace.directory = directory
        return r.workspace

    return cad.evaluate(
        case,
        r.settings,
        r.send,
        "crew-code-think",
        workspace_for=held,
        image_id=lambda: "sha256:abc",
        results_dir=r.results,
        read_spend=lambda _sql: "",
        **{"serving_record": lambda: {"serving_image": "lmsysorg/sglang:test"}, **kw},
    )


def test_an_assembly_made_to_spec_passes_and_its_row_says_so(tmp_path: Path) -> None:
    case = CASES["pin-clevis"]
    by = {f"{m.name}.step": measured(m) for m in case.members}
    for m in case.members:
        by[f"{m.name}.step"]["against"] = {
            g.other: {"interference": 0.0, "distance": g.distance[0]} for g in m.gaps
        }
    r = Run(tmp_path, DONE)
    r.workspace.measured_by = by
    row = go(r, "pin-clevis")
    assert (row["ending"], row["kind"], row["tier"]) == ("done", "assembly", 7)
    assert (row["compiles"], row["closed_mesh"], row["within_tolerance"]) == (True, True, True)
    assert (row["parts_total"], row["parts_fit"], row["fault"], row["load_ok"]) == (
        3,
        3,
        None,
        None,
    )
    # The case's own prompt and `done`, and its files named.
    assert r.bodies[0]["messages"][0]["content"] == system_for(CASES["pin-clevis"].outputs())
    done = [t for t in r.bodies[0]["tools"] if t["function"]["name"] == "done"][0]
    assert "`clevis.step`, `tongue.step`, `pin.step`" in done["function"]["description"]
    checked = json.loads((r.records(row) / "checks.json").read_text())
    assert {c["member"] for c in checked["checks"]} == {"clevis", "tongue", "pin"}
    assert results.problems(json.loads((r.results / "cad_eval.jsonl").read_text())) == []


def test_an_assembly_whose_parts_overlap_is_the_models_fault(tmp_path: Path) -> None:
    case = CASES["pin-clevis"]
    by = {f"{m.name}.step": measured(m) for m in case.members}
    for m in case.members:
        by[f"{m.name}.step"]["against"] = {
            g.other: {"interference": 4.2, "distance": 0.0} for g in m.gaps
        }
    r = Run(tmp_path, DONE)
    r.workspace.measured_by = by
    row = go(r, "pin-clevis")
    assert (row["within_tolerance"], row["parts_fit"], row["fault"]) == (False, 1, "model")


def test_a_worded_part_reports_its_load_check(tmp_path: Path) -> None:
    m = CASES["shelf-bracket"].members[0]
    thin = {
        "area": 24.0,
        "centroid": [20, 0, -1.5],
        "moments": [[0, 0, 0], [0, 18.0, 0], [0, 0, 128.0]],
        "bbox": [[20, 20], [-4, 4], [-3, 0]],
    }
    cylinders = [
        {"radius": 2.25, "axis": [1, 0, 0], "origin": [0, y, z], "hole": True}
        for y, z in ((8, -25), (-8, -55))
    ]
    r = Run(tmp_path, DONE)
    r.workspace.measured = measured(m, section=thin, cylinders=cylinders)
    row = go(r, "shelf-bracket")
    assert (row["kind"], row["load_ok"], row["within_tolerance"], row["fault"]) == (
        "worded",
        False,
        False,
        "model",
    )


def test_a_case_that_never_finishes_is_counted_with_no_checks(tmp_path: Path) -> None:
    r = Run(tmp_path, [answer(), answer(), answer()])
    row = go(r, "m8-bolt")
    assert (row["ending"], row["stop"], row["fault"]) == ("blocked", "no_tool_call", "model")
    assert row["parts_fit"] is None and row["compiles"] is None


@pytest.mark.parametrize("name", list(CASES))
def test_each_cases_prompt_names_every_file_it_must_write(name: str) -> None:
    prompt = system_for(CASES[name].outputs())
    for output in CASES[name].outputs():
        assert f"`{output}`" in prompt
    assert prompt != SYSTEM


def test_a_one_part_case_is_told_part_step(tmp_path: Path) -> None:
    r = Run(tmp_path, [answer(), answer(), answer()])
    go(r, "shelf-bracket")
    assert "the part as STEP to `part.step`" in r.bodies[0]["messages"][0]["content"]


def test_the_30_parts_rows_have_none_of_the_cases_fields(tmp_path: Path) -> None:
    from tests.cad_eval.test_checks import measured as part_measured  # noqa: PLC0415
    from tests.cad_eval.test_run import GOOD  # noqa: PLC0415

    row = Run(tmp_path, GOOD, measured=part_measured("spacer")).go()
    assert not {"kind", "parts_total", "parts_fit", "load_ok", "fault", "overhang_mm2"} & set(row)


def test_overhangs_are_recorded_for_the_members_that_passed_only() -> None:
    case = CASES["pin-clevis"]
    measured_by = {}
    for m in case.members:
        found = measured(m, print={"overhang_mm2": 10.0, "bridges": 1, "longest_bridge_mm": 2.5})
        found["against"] = {
            g.other: {"interference": 0.0, "distance": g.distance[0]} for g in m.gaps
        }
        measured_by[m.name] = found
    measured_by["pin"]["against"]["clevis"]["interference"] = 3.0
    row, found = cad.judge(case, {"code": 0, "measured": measured_by})
    assert (row["parts_fit"], row["overhang_mm2"], row["bridges"]) == (2, 20.0, 2)
    assert row["longest_bridge_mm"] == 2.5
    # Never a check.
    assert not any("overhang" in c["name"] or "bridge" in c["name"] for c in found)
    assert all(r.get("print") for r in cad.requests(case).values())


def test_other_calls_count_what_overlapped_but_not_the_runs_own(tmp_path: Path) -> None:
    from tests.cad_eval.test_checks import measured as part_measured  # noqa: PLC0415
    from tests.cad_eval.test_run import GOOD  # noqa: PLC0415

    replies = [dict(reply, id=f"chatcmpl-{n}") for n, reply in enumerate(GOOD)]
    log = "\n".join(
        [f"chatcmpl-{n}|claude-builders|crew-code-think" for n in range(4)]
        + ["other-1|claude-builders|crew-code-think", "tick-1|crew|crew-code-think"]
    )
    row = Run(tmp_path, replies, measured=part_measured("spacer")).go(read_spend=lambda _sql: log)
    assert (row["other_calls"], row["other_aliases"]) == (2, "claude-builders+crew")
    assert cad.own_calls(Path("nowhere")) == set()


def test_a_case_is_capped_by_calls_never_by_model_time(tmp_path: Path) -> None:
    import time  # noqa: PLC0415

    replies = [answer(call("write", {"path": "a.py", "content": ""}, n)) for n in range(5)]
    replies.append(answer(call("done", {"script": "a.py"})))
    r = Run(tmp_path, replies)
    clock = iter(range(0, 100_000, 2000))
    original = time.monotonic
    try:
        time.monotonic = lambda: next(clock)  # every call "takes" 2000 s
        row = go(r, "living-hinge")
    finally:
        time.monotonic = original
    assert row["stop"] != "backstop" and row["calls"] == 6


def test_a_lines_period_is_its_mean_rise_to_rise() -> None:
    """A thread's pitch, measured (the second review of #41: 1.15 and 1.3 passed)."""
    pitch = line("pitch", (0, 0, 0), (0, 0, 10), n=101, period=(1.23, 1.27))
    # In for 6 points, out for 6.5 on average: rises 12.5 points apart, 0.1 mm each.
    inside = [(k * 2) % 25 < 12 for k in range(101)]
    found = checks.sampled(pitch, inside)
    assert [c.name for c in found] == ["period.pitch"]
    assert abs(found[0].found - 1.25) < 0.01 and found[0].ok
    short = [(k % 12) < 6 for k in range(101)]  # 1.2 mm
    assert not checks.sampled(pitch, short)[0].ok


def test_a_cylinder_holds_its_radius_and_its_place_apart() -> None:
    """The second review of #41: one probe held a bore's size and place together, and
    failed a correct bore moved 0.04 mm."""
    from cad_eval.cases import Cylinder  # noqa: PLC0415

    bore = Cylinder("bore", "z", (0, 0, 4), (2.975, 3.025), offset=0.1)

    def face(radius: float, x: float, hole: bool = True) -> dict:
        return {"radius": radius, "axis": [0, 0, 1], "origin": [x, 0, 0], "hole": hole}

    moved = checks.cylinder(bore, [face(3.0, 0.04)])
    assert all(c.ok for c in moved)
    assert [c.name for c in checks.cylinder(bore, [face(3.06, 0.0)]) if not c.ok] == [
        "cylinder.bore.radius"
    ]
    assert [c.name for c in checks.cylinder(bore, [face(3.0, 0.15)]) if not c.ok] == [
        "cylinder.bore.position"
    ]
    # An outer face isn't a hole, and nothing near is a fail, never a pass.
    assert not checks.cylinder(bore, [face(3.0, 0.0, hole=False)])[0].ok
    # Of several on the axis (a pin inside a knuckle), the radius nearest the spec's.
    pin = Cylinder("pin", "z", (0, 0, 0), (1.475, 1.525), kind="outer")
    both = [face(1.5, 0, hole=False), face(3.0, 0, hole=False)]
    assert all(c.ok for c in checks.cylinder(pin, both))


def test_a_box_holds_each_size_to_its_own_tolerance() -> None:
    m = Member("m", bbox=((0, 30), (0, 24), (0, 10)))
    both_ends_off = measured(m, bbox=[[-0.09, 30.09], [0, 24], [0, 10]])
    failed = [c.name for c in checks.member(m, both_ends_off) if not c.ok]
    # Each end within its 0.1, but the size 0.18 over.
    assert failed == ["size.x"]


def test_a_cylinder_holds_every_face_near_its_radius() -> None:
    """Two coaxial holes (a fork's): a wrong one fails though the other is right."""
    from cad_eval.cases import Cylinder  # noqa: PLC0415

    hole = Cylinder("hole", "y", (0, 0, 0), (2.625, 2.675))

    def face(radius: float, z: float = 0.0) -> dict:
        return {"radius": radius, "axis": [0, 1, 0], "origin": [0, 0, z], "hole": True}

    assert all(c.ok for c in checks.cylinder(hole, [face(2.65), face(2.66)]))
    assert not checks.cylinder(hole, [face(2.65), face(2.75)])[0].ok
    assert not checks.cylinder(hole, [face(2.65), face(2.65, z=0.2)])[1].ok
