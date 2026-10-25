"""The parts, each a spec as a person would write it and the checks that say it's right.

The specs are written here, from scratch, modelled on functional printed parts: the
kind the print project (M13) prints. Each is `parts/<name>.md`, the text the model is
given. The tiers follow the simple-to-complex split of the CAD-code benchmarks
(CADPrompt, Text2CAD), up to a part with an interface to another part:

1. one primitive with features;
2. several features (fillets, holes on two faces);
3. shells and patterns;
4. sweeps, lofts and revolves;
5. a fit to a mating part.

A part's checks are data, compared by `cad_eval/checks.py` with what
`cad_eval/measure.py` measures in the container: the bounding box (which fixes the
spec's placement too), the volume, points that must be inside or outside the
material, and, for a fit, the overlap with the mating part. Each part's reference
solution, in `tests/cad_eval/reference/`, passes them, and a planted wrong one fails.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

SPECS = Path(__file__).parent / "parts"
Point = tuple[float, float, float]


@dataclass(frozen=True)
class Part:
    name: str
    tier: int
    # The expected bounding box, (low, high) along X, Y and Z, each within `tol` mm.
    bbox: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    volume: float  # mm³, within `volume_rel` of it
    tol: float = 0.1
    volume_rel: float = 0.02
    solids: int = 1
    # Named points that must be in the material, or out of it: each a feature.
    inside: dict[str, Point] = field(default_factory=dict)
    outside: dict[str, Point] = field(default_factory=dict)
    # A mating part's CadQuery source, naming it `mate`, and the overlap allowed with it.
    mate: str | None = None
    max_interference: float = 0.01

    def spec(self) -> str:
        return (SPECS / f"{self.name}.md").read_text(encoding="utf-8")

    def probes(self) -> list[Point]:
        return [*self.inside.values(), *self.outside.values()]


def _tube(outer: float, inner: float, length: float) -> float:
    return math.pi / 4 * (outer**2 - inner**2) * length


def _slot(width: float, length: float) -> float:
    return (length - width) * width + math.pi * (width / 2) ** 2


# The box the lid fits, as `box-lid.md` describes it.
OPEN_BOX = """
mate = (
    cq.Workplane("XY").box(60, 40, 30, centered=(True, True, False))
    .faces(">Z").shell(-2)
)
"""

# The mating parts of tier 5, as their specs describe them.
SHAFT = "mate = cq.Workplane('XY').workplane(offset=-20).circle(4).extrude(60)"
BEARING = "mate = cq.Workplane('XY').workplane(offset=2).circle(11).extrude(7)"
RAIL = "mate = cq.Workplane('XY').box(100, 20, 10, centered=(True, True, False))"
PANEL = """
mate = (
    cq.Workplane("XY").box(40, 40, 5, centered=(True, True, False))
    .faces(">Z").workplane().hole(20)
)
"""
TUBES = """
low = cq.Workplane("XY").workplane(offset=-20).circle(5).circle(3.5).extrude(19.5)
high = cq.Workplane("XY").workplane(offset=0.5).circle(5).circle(3.5).extrude(19.5)
mate = low.union(high)
"""

PARTS = {
    p.name: p
    for p in (
        Part(
            "spacer",
            1,
            bbox=((-6, 6), (-6, 6), (0, 10)),
            volume=_tube(12, 5.3, 10),
            # The bore's edges at ±0.05 mm of radius: its diameter within ±0.1 mm.
            inside={"wall": (4.3, 0, 5), "bore_at_most": (2.7, 0, 5)},
            outside={"bore": (0, 0, 5), "bore_at_least": (0, 2.6, 5), "bore_top": (0, 0, 9.9)},
        ),
        Part(
            "l-bracket",
            2,
            bbox=((0, 50), (-20, 20), (0, 50)),
            volume=(
                50 * 40 * 4
                + 4 * 40 * 46
                + (5**2 - math.pi * 5**2 / 4) * 40
                - 4 * math.pi * 2.75**2 * 4
            ),
            inside={"base": (25, 0, 2), "upright": (2, 0, 25), "fillet": (5.0, 0, 5.0)},
            outside={
                "base_hole_+y": (35, 10, 2),
                "base_hole_-y": (35, -10, 2),
                "upright_hole_+y": (2, 10, 35),
                "upright_hole_-y": (2, -10, 35),
                "past_fillet": (6.5, 0, 6.5),
                "above_base": (25, 0, 6),
            },
        ),
        Part(
            "vented-box",
            3,
            bbox=((-30, 30), (-20, 20), (0, 30)),
            volume=60 * 40 * 30 - 56 * 36 * 28 - 5 * _slot(3, 30) * 2,
            inside={
                "wall_x": (29, 0, 15),
                "wall_y": (0, 19, 15),
                "floor_between": (4, 0, 1),
                "floor_past_slot": (0, 16.5, 1),
            },
            outside={
                "cavity": (0, 0, 15),
                "slot_-16": (-16, 0, 1),
                "slot_-8": (-8, 0, 1),
                "slot_0": (0, 10, 1),
                "slot_8": (8, -10, 1),
                "slot_16": (16, 0, 1),
                "open_top": (0, 0, 29.5),
            },
        ),
        Part(
            "hose-elbow",
            4,
            bbox=((-5, 35), (-5, 5), (0, 40)),
            volume=_tube(10, 7, 15 + 15 + math.pi / 2 * 20),
            inside={
                "wall_first": (4.25, 0, 7),
                "wall_bend": (20 - 24.25 * math.sqrt(0.5), 0, 15 + 24.25 * math.sqrt(0.5)),
                "wall_last": (28, 0, 39.25),
                # The bore's edge at 0.05 mm of radius: its diameter at most 7.1 mm.
                "bore_at_most": (3.55, 0, 7),
            },
            outside={
                "bore_first": (0, 0, 7),
                "bore_at_least": (0, 3.45, 7),
                "bore_bend": (20 - 20 * math.sqrt(0.5), 0, 15 + 20 * math.sqrt(0.5)),
                "bore_last": (28, 0, 35),
                "inside_bend": (25, 0, 25),
            },
        ),
        Part(
            "box-lid",
            5,
            bbox=((-30, 30), (-20, 20), (26, 32)),
            volume=60 * 40 * 2 + (55.6 * 35.6 - 52.6 * 32.6) * 4,
            inside={
                "plate": (0, 0, 31),
                "lip_x": (27.05, 0, 28),
                "lip_y": (0, 17.05, 28),
                # The lip reaches out far enough: the clearance is at most 0.35 mm.
                "lip_x_reach": (27.65, 0, 28),
                "lip_y_reach": (0, 17.65, 28),
            },
            outside={
                "under_plate": (0, 0, 28),
                # And no further: the clearance is at least 0.05 mm.
                "gap_x": (27.95, 0, 28),
                "gap_y": (0, 17.95, 28),
                "below_lip": (27.05, 0, 25.5),
            },
            mate=OPEN_BOX,
        ),
        # Tier 1: one primitive with features.
        Part(
            "washer",
            1,
            bbox=((-10, 10), (-10, 10), (0, 2)),
            volume=_tube(20, 10.5, 2),
            inside={"ring": (7.5, 0, 1), "hole_at_most": (5.3, 0, 1)},
            outside={"hole": (0, 0, 1), "hole_at_least": (0, 5.2, 1)},
        ),
        Part(
            "square-plate",
            1,
            bbox=((-25, 25), (-25, 25), (0, 3)),
            volume=50 * 50 * 3 - 4 * math.pi * 1.7**2 * 3,
            inside={"plate": (0, 0, 1.5), "hole_at_most": (21.75, 20, 1.5)},
            outside={
                **{f"hole_{x:+d}_{y:+d}": (x, y, 1.5) for x in (20, -20) for y in (20, -20)},
                "hole_at_least": (21.65, 20, 1.5),
            },
        ),
        Part(
            "hex-standoff",
            1,
            bbox=((-8 / math.sqrt(3), 8 / math.sqrt(3)), (-4, 4), (0, 15)),
            volume=(math.sqrt(3) / 2 * 8**2 - math.pi * 1.6**2) * 15,
            inside={
                "body": (3, 0, 7.5),
                "corner_on_x": (4.5, 0, 7.5),
                "bore_at_most": (1.65, 0, 7.5),
            },
            outside={
                "bore": (0, 0, 7.5),
                "bore_at_least": (0, 1.55, 7.5),
                "past_flat": (0, 4.3, 7.5),
            },
        ),
        Part(
            "end-cap",
            1,
            bbox=((-8, 8), (-8, 8), (0, 12)),
            volume=math.pi / 4 * (16**2 * 12 - 10**2 * 10),
            inside={
                "top": (0, 0, 11),
                "top_at_least": (0, 0, 10.1),
                "wall": (6.5, 0, 5),
                "hole_at_most": (5.05, 0, 5),
            },
            outside={"hole": (0, 0, 5), "hole_depth": (0, 0, 9.9), "hole_at_least": (0, 4.95, 5)},
        ),
        Part(
            "slotted-bar",
            1,
            bbox=((-40, 40), (-6, 6), (0, 5)),
            volume=80 * 12 * 5 - _slot(5.5, 40) * 5,
            inside={"bar": (30, 0, 2.5), "slot_end": (20.1, 0, 2.5), "slot_side": (0, 2.85, 2.5)},
            outside={
                "slot": (0, 0, 2.5),
                "slot_reach": (19.9, 0, 2.5),
                "slot_width": (0, 2.7, 2.5),
            },
        ),
        # Tier 2: several features.
        Part(
            "flanged-bushing",
            2,
            bbox=((-10, 10), (-10, 10), (0, 15)),
            volume=math.pi / 4 * (20**2 * 3 + 12**2 * 12 - 8**2 * 15),
            inside={"flange": (9, 0, 1.5), "body": (5, 0, 10), "bore_at_most": (4.05, 0, 10)},
            outside={
                "over_flange": (9, 0, 5),
                "body_at_most": (0, 6.1, 10),
                "bore": (0, 0, 7),
                "bore_at_least": (0, 3.95, 10),
            },
        ),
        Part(
            "motor-plate",
            2,
            bbox=((-30, 30), (-30, 30), (0, 4)),
            volume=(
                60 * 60 * 4
                - 4 * (5**2 - math.pi * 5**2 / 4) * 4
                - math.pi * 11**2 * 4
                - 4 * math.pi * 1.7**2 * 4
            ),
            inside={
                "plate": (20, 0, 2),
                "corner_rounded_in": (28, 28, 2),
                "boss_at_most": (11.05, 0, 2),
            },
            outside={
                "corner_rounded_out": (29.5, 29.5, 2),
                "boss": (0, 0, 2),
                "boss_at_least": (0, 10.95, 2),
                **{
                    f"hole_{x:+.1f}_{y:+.1f}": (x, y, 2)
                    for x in (15.5, -15.5)
                    for y in (15.5, -15.5)
                },
            },
        ),
        Part(
            "stepped-shaft",
            2,
            bbox=((-10, 10), (-10, 10), (0, 40)),
            volume=math.pi / 4 * (20**2 * 10 + 14**2 * 20 + 8**2 * 10) - 2 * math.pi * 11 / 3 * 0.5,
            inside={
                "collar": (9, 0, 5),
                "seat": (6.5, 0, 20),
                "end": (3.5, 0, 35),
                "by_chamfer": (3.5, 0, 39.3),
            },
            outside={
                "over_collar": (9, 0, 15),
                "over_seat": (6.5, 0, 35),
                "chamfer": (3.8, 0, 39.8),
            },
        ),
        Part(
            "u-channel",
            2,
            bbox=((0, 60), (-15, 15), (0, 20)),
            volume=(30 * 3 + 2 * 3 * 17) * 60 - 2 * math.pi * 2.25**2 * 3,
            inside={
                "floor": (30, 0, 1.5),
                "wall_+y": (30, 13.5, 10),
                "wall_-y": (30, -13.5, 10),
                "wall_thickness": (30, 12.1, 10),
            },
            outside={"channel": (30, 0, 10), "hole_15": (15, 0, 1.5), "hole_45": (45, 0, 1.5)},
        ),
        Part(
            "counterbored-block",
            2,
            bbox=((-20, 20), (-10, 10), (0, 15)),
            volume=40 * 20 * 15 - 2 * (math.pi * 2.25**2 * 10.5 + math.pi * 4**2 * 4.5),
            inside={
                "block": (0, 0, 7.5),
                "below_counterbore": (12, 3.5, 5),
                "counterbore_floor": (12, 3.5, 10.4),
            },
            outside={
                "hole_+12": (12, 0, 5),
                "hole_-12": (-12, 0, 5),
                "counterbore": (12, 3.5, 13),
                "counterbore_-12": (-12, -3.5, 13),
                "counterbore_depth": (12, 3.5, 10.6),
            },
        ),
        # Tier 3: shells and patterns.
        Part(
            "pegboard-plate",
            3,
            bbox=((-30, 30), (-20, 20), (0, 3)),
            volume=60 * 40 * 3 - 15 * math.pi * 2.5**2 * 3,
            inside={"between": (5, 5, 1.5), "hole_at_most": (2.55, 0, 1.5)},
            outside={
                **{f"hole_{x:+d}_{y:+d}": (x, y, 1.5) for x in (-20, 0, 20) for y in (-10, 10)},
                "hole_0_0": (0, 0, 1.5),
                "hole_at_least": (0, 2.45, 1.5),
            },
        ),
        Part(
            "cup",
            3,
            bbox=((-25, 25), (-25, 25), (0, 40)),
            volume=math.pi / 4 * (50**2 * 40 - 46**2 * 37),
            inside={
                "wall": (24, 0, 20),
                "floor": (0, 0, 1.5),
                "floor_at_least": (0, 0, 2.9),
                "wall_at_least": (23.1, 0, 20),
            },
            outside={
                "cavity": (0, 0, 20),
                "floor_at_most": (0, 0, 3.1),
                "wall_at_most": (0, 22.9, 20),
            },
        ),
        Part(
            "bolt-flange",
            3,
            bbox=((-40, 40), (-40, 40), (0, 6)),
            volume=math.pi / 4 * (80**2 - 30**2) * 6 - 6 * math.pi / 4 * 6.5**2 * 6,
            inside={
                "disc": (20, 0, 3),
                "between_holes": (30 * math.cos(math.pi / 6), 15, 3),
                "bore_at_most": (0, 15.05, 3),
            },
            outside={
                "bore": (0, 0, 3),
                "bore_at_least": (14.95, 0, 3),
                **{
                    f"hole_{k}": (30 * math.cos(k * math.pi / 3), 30 * math.sin(k * math.pi / 3), 3)
                    for k in range(6)
                },
            },
        ),
        Part(
            "heat-sink",
            3,
            bbox=((-20, 20), (-20, 20), (0, 18)),
            volume=40 * 40 * 3 + 7 * 1.5 * 40 * 15,
            inside={
                "base": (3, 0, 1.5),
                "fin_0": (0, 0, 10),
                "fin_+18": (18, 0, 10),
                "fin_-18": (-18, 0, 10),
                "fin_full_length": (-12, 19.5, 17),
                "fin_thickness": (0.7, 0, 10),
            },
            outside={
                "gap_+3": (3, 0, 10),
                "gap_-15": (-15, 0, 10),
                "past_fin": (19.5, 0, 10),
                "fin_at_most": (0.8, 0, 10),
            },
        ),
        Part(
            "divided-tray",
            3,
            bbox=((-40, 40), (-30, 30), (0, 20)),
            volume=80 * 60 * 20 - 76 * 56 * 18 + 2 * 56 * 18,
            inside={
                "divider": (0, 0, 10),
                "divider_joins": (0, 28.5, 19),
                "wall": (39, 0, 10),
                "floor": (20, 0, 1),
            },
            outside={
                "compartment_+x": (20, 0, 10),
                "compartment_-x": (-20, 0, 10),
                "floor_at_most": (20, 0, 2.1),
            },
        ),
        # Tier 4: sweeps, lofts and revolves.
        Part(
            "funnel",
            4,
            bbox=((-31.5, 31.5), (-31.5, 31.5), (0, 40)),
            # Pappus: the spout's band, 1.5 by 10 at r 6.75, and the cone's, 1.5 by 30 at r 18.75.
            volume=2 * math.pi * (6.75 * 1.5 * 10 + 18.75 * 1.5 * 30),
            inside={"spout": (6.75, 0, 5), "cone": (18.75, 0, 25), "rim": (0, 30.75, 39.5)},
            outside={
                "spout_bore": (0, 0, 5),
                "inside_cone": (17.5, 0, 25),
                "outside_cone": (20.5, 0, 25),
                "open_top": (0, 0, 39),
            },
        ),
        Part(
            "tapered-foot",
            4,
            bbox=((-20, 20), (-20, 20), (0, 30)),
            volume=30 / 3 * (40**2 + 20**2 + 40 * 20) - math.pi * 3.25**2 * 30,
            inside={
                "low": (15, 0, 5),
                "high": (11, 0, 25),
                "corner": (18, 18, 2),
                "hole_at_most": (3.3, 0, 15),
            },
            outside={"tapered": (15, 0, 25), "hole": (0, 0, 15), "hole_at_least": (0, 3.2, 15)},
        ),
        Part(
            "coil-spring",
            4,
            bbox=((-11, 11), (-11, 11), (-1, 21)),
            volume=math.pi * 1**2 * 4 * math.hypot(2 * math.pi * 10, 5),
            inside={
                "half_turn": (-10, 0, 2.5),
                "quarter_turn": (0, 10, 1.25),
                "last_turn": (0, -10, 18.75),
            },
            outside={"axis": (0, 0, 10), "between_coils": (-10, 0, 5), "start_gap": (10, 0, 2.5)},
        ),
        Part(
            "pulley",
            4,
            bbox=((-20, 20), (-20, 20), (0, 12)),
            volume=math.pi * 20**2 * 12 - 2 * math.pi * (20 - 4 / 3) * 12 - math.pi * 4**2 * 12,
            inside={"rim": (19, 0, 1.5), "under_groove": (15.9, 0, 6), "bore_at_most": (0, 4.1, 6)},
            outside={
                "groove": (19, 0, 6),
                "groove_depth": (16.2, 0, 6),
                "bore": (0, 0, 6),
                "bore_at_least": (3.9, 0, 6),
            },
        ),
        Part(
            "drawer-handle",
            4,
            bbox=((-44, 44), (-4, 4), (0, 34)),
            volume=math.pi * 4**2 * (20 + 20 + 60 + math.pi * 10),
            inside={
                "leg_-x": (-40, 0, 10),
                "leg_+x": (40, 0, 10),
                "grip": (0, 0, 30),
                "grip_round": (0, 3.5, 30),
                "bend": (-30 - 10 * math.sqrt(0.5), 0, 20 + 10 * math.sqrt(0.5)),
            },
            outside={
                "under_grip": (0, 0, 25),
                "outside_bend": (-40, 0, 30),
                "over_grip": (0, 0, 34.5),
            },
        ),
        # Tier 5: a fit to a mating part.
        Part(
            "shaft-collar",
            5,
            bbox=((-9, 9), (-9, 9), (0, 10)),
            volume=math.pi / 4 * (18**2 - 8.2**2) * 10 - math.pi * 1.25**2 * (9 - 4.1),
            inside={"wall": (0, -8, 5), "bore_at_most": (0, -4.22, 5), "over_screw": (6.5, 0, 8)},
            outside={"bore": (0, 0, 5), "bore_at_least": (0, -4.03, 5), "set_screw": (6.5, 0, 5)},
            mate=SHAFT,
        ),
        Part(
            "bearing-housing",
            5,
            bbox=((-20, 20), (-20, 20), (0, 10)),
            volume=(
                40 * 40 * 10
                - math.pi / 4 * 22.1**2 * 8
                - math.pi / 4 * 16**2 * 2
                - 4 * math.pi * 2.25**2 * 10
            ),
            inside={
                "block": (18, 0, 5),
                "pocket_at_most": (0, -11.15, 6),
                "floor": (0, -9, 1),
                "floor_top": (0, -9, 1.9),
            },
            outside={
                "pocket": (0, 0, 6),
                "pocket_at_least": (11.02, 0, 6),
                "shaft_hole": (0, 0, 1),
                "over_floor": (0, -9, 2.1),
                **{f"hole_{x:+d}_{y:+d}": (x, y, 5) for x in (15, -15) for y in (15, -15)},
            },
            mate=BEARING,
        ),
        Part(
            "rail-slider",
            5,
            bbox=((-15, 15), (-15, 15), (0, 15)),
            volume=30 * 30 * 15 - 30 * 20.4 * 10.2,
            # The channel's clearance may run from 0.05 to 0.35 mm on each face.
            volume_rel=0.04,
            inside={
                "side": (0, 12.5, 5),
                "top": (0, 0, 12.5),
                "side_at_most": (0, -10.35, 5),
                "top_at_most": (0, 0, 10.35),
            },
            outside={
                "channel": (0, 0, 5),
                "side_at_least": (0, -10.05, 5),
                "top_at_least": (5, 0, 10.05),
            },
            mate=RAIL,
        ),
        Part(
            "hole-plug",
            5,
            bbox=((-13, 13), (-13, 13), (0, 7)),
            volume=math.pi / 4 * (26**2 * 2 + 19.8**2 * 5),
            inside={"shank": (0, 0, 2.5), "head": (12, 0, 6), "shank_at_least": (0, -9.8, 2.5)},
            outside={"under_head": (12, 0, 4), "shank_at_most": (9.97, 0, 2.5)},
            mate=PANEL,
        ),
        Part(
            "tube-coupler",
            5,
            bbox=((-7, 7), (-7, 7), (-15, 15)),
            volume=math.pi / 4 * ((14**2 - 10.2**2) * 30 + (10.2**2 - 7**2) * 1),
            # The bore's clearance may run from 0.1 to 0.4 mm.
            volume_rel=0.06,
            inside={
                "sleeve": (6, 0, 8),
                "bore_at_most": (0, -5.22, 8),
                "stop": (4.3, 0, 0),
                "stop_thickness": (4.3, 0, 0.4),
            },
            outside={
                "bore": (0, 0, 8),
                "bore_at_least": (5.03, 0, 8),
                "stop_hole": (0, 0, 0),
                "stop_at_most": (4.3, 0, 0.6),
            },
            mate=TUBES,
        ),
    )
}
# The first run's parts: one per tier.
FIRST = ("spacer", "l-bracket", "vented-box", "hose-elbow", "box-lid")


class UnknownPart(KeyError):
    pass


def part(name: str) -> Part:
    try:
        return PARTS[name]
    except KeyError:
        raise UnknownPart(f"no part {name!r}; the parts are {', '.join(PARTS)}") from None
