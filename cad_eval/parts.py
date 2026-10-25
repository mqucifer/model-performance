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
