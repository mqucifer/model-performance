"""The harder cases: tight features, assemblies, and specs in a person's words.

mqucifer/model-performance#16, M14's first step: find where the base model breaks. On
the 30 parts of `parts.py` the 27B passed 28, so these push past them, in three kinds
of increasing difficulty, each a tier after `parts.py`'s five:

6. `tight`: features with tight tolerances, one part: a living hinge, a press fit, a
   snap-fit hook, a dovetail, a print-in-place hinge, a gear, a thread;
7. `assembly`: two to five parts that must fit, each its own STEP file, placed as
   assembled, with the interfaces between them as checks;
8. `worded`: a part asked for as a person would ("holds a 2 kg shelf"), with the
   dimensions the model's to choose, and the checks the bounds a working part must
   keep, the features it must have, and a simplified load check.

Each case is `parts/<name>.md`, the text the model is given, and its checks as data,
compared by `cad_eval/checks.py` with what `cad_eval/measure.py` measures in the
container. Each case's reference solution in `tests/cad_eval/reference/` passes
them, and a planted wrong one in `tests/cad_eval/wrong/` fails. Where each comes
from is in `cad_eval/README.md`.

**A fit's expected interference is part of its spec:** a press fit must overlap its
mating part, within a range; a clearance fit must not, and its gap, the closest
distance between the two, must be within the spec's clearance.

**The load check is a simplification, and is said to be one.** It's the bending
stress at one section, from the stated load at a stated arm, against PLA's strength
over a safety factor (`Load`). It passes or fails that check only: it never says a
part is strong enough.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

SPECS = Path(__file__).parent / "parts"
Point = tuple[float, float, float]
Box = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
Span = tuple[float, float]

KINDS = {6: "tight", 7: "assembly", 8: "worded"}
# Volumes measured off the reference solution, where no formula is short: within
# `volume_rel` of these.
VOLUMES = {
    "print-in-place-hinge": 4749.278,
    "spur-gear": 5290.916,
    "gear-a": 1322.276,
    "gear-b": 8049.99,
}
# Gear B's bounding box, off the reference: no tooth of it is on an axis.
BOXES: dict[str, Box] = {"gear-b": ((7.7867, 52.6133), (-22.4133, 22.4133), (4.5, 10.5))}
# A hexagon 13 mm across its flats.
HEX_AREA = 2 * math.sqrt(3) * 6.5**2

# PLA's strength for the load check, and the factor it's divided by. Ultimaker PLA's
# technical data sheet (v5.00): yield strength 52.5 MPa, printed flat (XY), ASTM
# D3039. Printed upright (Z), it shows no yield and breaks lower, across its layers;
# the factor of 4 covers that, the infill, and creep under a standing load.
PLA_STRENGTH_MPA = 52.5
SAFETY_FACTOR = 4.0
ALLOWED_MPA = PLA_STRENGTH_MPA / SAFETY_FACTOR
G = 9.81


@dataclass(frozen=True)
class Sample:
    """Points along a line or round a circle, and how they must meet the material.

    `share` is the range of the points' share inside. `changes` is the range of times
    they go from inside to outside or back, in order (round a circle, back to the
    first): a gear's teeth or a thread's turns, counted. `gaps`, for a line, is the
    range of each gap's width in mm: each run of points outside the material between
    two inside it, a comb's slot.
    """

    name: str
    points: tuple[Point, ...]
    share: Span = (0.0, 1.0)
    changes: tuple[int, int] | None = None
    closed: bool = False
    gaps: Span | None = None
    spacing: float = 0.0  # between points along a line, mm


def ring(
    name: str,
    centre: Point,
    radius: float,
    *,
    axis: str = "z",
    n: int = 360,
    share: Span = (0.0, 1.0),
    changes: tuple[int, int] | None = None,
) -> Sample:
    """`n` points round a circle of `radius` about `axis` through `centre`."""
    i, j = [k for k in range(3) if k != "xyz".index(axis)]
    points = []
    for step in range(n):
        angle = 2 * math.pi * step / n
        p = list(centre)
        p[i] += radius * math.cos(angle)
        p[j] += radius * math.sin(angle)
        points.append((round(p[0], 3), round(p[1], 3), round(p[2], 3)))
    return Sample(name, tuple(points), share, changes, closed=True)


def line(
    name: str,
    start: Point,
    end: Point,
    *,
    n: int = 200,
    share: Span = (0.0, 1.0),
    changes: tuple[int, int] | None = None,
    gaps: Span | None = None,
) -> Sample:
    """`n` points from `start` to `end`, both included."""
    points = tuple(
        tuple(round(a + (b - a) * k / (n - 1), 3) for a, b in zip(start, end, strict=True))
        for k in range(n)
    )
    spacing = math.dist(start, end) / (n - 1)
    return Sample(name, points, share, changes, gaps=gaps, spacing=spacing)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Holes:
    """Round holes the part must have, wherever the model puts them: at least `count`
    cylindrical hole faces along `axis`, of a radius within `radius`, on distinct axes."""

    name: str
    axis: str
    radius: Span
    count: int = 1


@dataclass(frozen=True)
class Load:
    """The simplified load check: bending stress at one section, under a stated load.

    The section is the material in the plane `axis` = `at`, measured in the container.
    The load is `force_n` along `along` (downward, -Z, for a weight), at `arm_mm` from
    the section, so the moment is their product. Without `arm_mm` the load hangs at the
    part's far end along `axis`, the worst place it could, so a longer part carries a
    longer arm. The stress is M·c/I, with I the
    section's second moment about its centroid across the load, and c the farthest
    material from that centroid along the load. It passes at no more than
    `ALLOWED_MPA`. It ignores the screws, shear, the stress raised at corners, and
    the layers' direction: a check that a section isn't far too thin, no more.
    """

    name: str
    axis: str
    at: float
    force_n: float
    arm_mm: float | None = None
    along: str = "z"


@dataclass(frozen=True)
class Vents:
    """Open area through a part along `axis`: lines on a grid of `step` mm over the
    rectangle `over` (the range along each of the two axes across it, in order), each
    open where it meets no material. The open area is the open lines times `step`²: at
    least `area` mm²."""

    name: str
    over: tuple[tuple[float, float], tuple[float, float]]
    area: float
    step: float = 3.0
    axis: str = "z"

    def points(self) -> list[tuple[float, float]]:
        (a0, a1), (b0, b1) = self.over
        na, nb = int((a1 - a0) / self.step) + 1, int((b1 - b0) / self.step) + 1
        return [
            (round(a0 + i * self.step, 3), round(b0 + j * self.step, 3))
            for i in range(na)
            for j in range(nb)
        ]


@dataclass(frozen=True)
class Gap:
    """How a member meets another part: a mate the case gives, or another member.

    `interference` is the range of the overlap's volume, mm³: (0, 0.01) for a
    clearance fit, above zero for a press fit. `distance`, when given, is the range of
    the closest distance between them: a clearance fit's gap. Two parts in contact
    or overlapping are at distance 0.
    """

    other: str
    interference: Span = (0.0, 0.01)
    distance: Span | None = None


@dataclass(frozen=True)
class Member:
    """One part of a case, its own STEP file, `<name>.step`, and its checks.

    Each check is optional, so a worded part can have bounds where a tight one has
    dimensions: `bbox` exactly (within `tol`), or `within` a box with each axis'
    extent in `spans`; `volume` (within `volume_rel`) or a `volume_range`.
    """

    name: str
    solids: int = 1
    bbox: Box | None = None
    tol: float = 0.1
    within: Box | None = None
    spans: tuple[Span | None, Span | None, Span | None] | None = None
    volume: float | None = None
    volume_rel: float = 0.02
    volume_range: Span | None = None
    inside: dict[str, Point] = field(default_factory=dict)
    outside: dict[str, Point] = field(default_factory=dict)
    samples: tuple[Sample, ...] = ()
    holes: tuple[Holes, ...] = ()
    load: Load | None = None
    gaps: tuple[Gap, ...] = ()
    # The range of the closest distance between the member's own solids, which must
    # not overlap: a print-in-place joint's clearance.
    own_gap: Span | None = None
    vents: Vents | None = None

    def probes(self) -> list[Point]:
        found = [*self.inside.values(), *self.outside.values()]
        for sample in self.samples:
            found.extend(sample.points)
        return found


@dataclass(frozen=True)
class Case:
    name: str
    tier: int
    members: tuple[Member, ...]
    # Mating parts the case gives, by name: CadQuery source that names the part `mate`.
    mates: dict[str, str] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return KINDS[self.tier]

    def spec(self) -> str:
        return (SPECS / f"{self.name}.md").read_text(encoding="utf-8")

    def outputs(self) -> list[str]:
        return [f"{m.name}.step" for m in self.members]


def helix(name: str, radius: float, pitch: float, z0: float, z1: float, n: int = 360) -> Sample:
    """`n` points along a right-hand helix: in a right-hand thread of the same pitch they
    keep to one side of its flanks, so they change from inside to out hardly at all."""
    points = []
    for k in range(n):
        z = z0 + (z1 - z0) * k / (n - 1)
        a = 2 * math.pi * z / pitch
        points.append((round(radius * math.cos(a), 3), round(radius * math.sin(a), 3), round(z, 3)))
    return Sample(name, tuple(points), (0.0, 1.0), (0, 2))


# The mating parts the tight cases give, as their specs describe them.
BLOCK = """
mate = (
    cq.Workplane("XY").box(20, 20, 10, centered=(True, True, False))
    .faces(">Z").workplane().hole(5)
)
"""
LEDGE = "mate = cq.Workplane('XY').box(4.9, 12, 6.9, centered=False).translate((5.1, -6, 10))"
DOVETAIL = """
mate = (
    cq.Workplane("XY").box(60, 20, 5, centered=(True, True, False))
    .union(
        cq.Workplane("YZ").polyline([(-5, 5), (5, 5), (7, 10), (-7, 10)]).close()
        .extrude(30, both=True)
    )
)
"""
# The worded cases': the shaft the knob fits, as its spec describes it.
D_SHAFT = """
mate = (
    cq.Workplane("XY").circle(3).extrude(12)
    .cut(cq.Workplane("XY").box(5, 10, 12, centered=(False, True, False)).translate((1.5, 0, 0)))
)
"""

# The Sponsor's case's boards, from their published drawings, in its frame: the Pi's top
# face at Z = 0, the board from X = 0 to 85 and Y = 0 to 56 (Raspberry Pi Ltd,
# "Raspberry Pi 5" mechanical drawing, in the Pi 5 product brief, p. 3). Neither maker
# publishes a board's thickness, so nothing here depends on one.
#
# The Pi, 0.5 mm clear all round (its 85 × 56 outline), from 13 mm below its top (its
# own thickness and the kit's 12 mm standoffs, the least it could be) to 4.4 mm above
# it, the tallest part the drawing dimensions: the gap the SSDs sit in, and the board.
# Columns 3 mm round its 2.7 mm holes (58 × 49 mm, 3.5 mm in) are left for the standoffs.
PI5_HOLES = [(x, y) for x in (3.5, 61.5) for y in (3.5, 52.5)]
PI5_KEEP_OUT = f"""
mate = cq.Workplane("XY").box(86, 57, 17.4, centered=False).translate((-0.5, -0.5, -13))
for x, y in {PI5_HOLES!r}:
    mate = mate.cut(cq.Workplane("XY").workplane(offset=-14).center(x, y).circle(3).extrude(20))
"""
# The NVMe Base Duo (Pimoroni, "nvme-base-duo-drawing.png" on its product page): 87.60
# mm long, its holes 4.50 mm in from its flex cable's edge and 3.50 mm from its bottom
# edge, on the Pi's pattern, so it runs from X = -1.0 to 86.6. Pimoroni gives no height
# along Y and no thickness: it's kept out only from its bottom edge to its far holes'
# line (Y = 0 to 52.5), 0.5 mm clear, and through 1 mm below its top, the least board
# it could be.
NVME_BASE_KEEP_OUT = (
    "mate = cq.Workplane('XY').box(88.6, 53, 1.6, centered=False).translate((-1.5, -0.5, -14.6))"
)
# Each port's axis, out through the walls, must be clear (the Pi 5 drawing): USB-C at X =
# 11.2 and the micro HDMIs at 25.8 and 39.2 on the Y = 0 edge, half their published
# heights above the board (3.2 and 3.4 mm); Ethernet at Y = 10.2 and the USBs at 29.1
# and 47 on the X = 85 edge, past their 3 mm overhang, 1 mm above the board, which
# they stand on. Their heights aren't published, nor the microSD's place: not checked.
PI5_PORTS = (
    line("usb_c", (11.2, -0.6, 1.6), (11.2, -20, 1.6), n=60, share=(0.0, 0.0)),
    line("hdmi_0", (25.8, -0.6, 1.7), (25.8, -20, 1.7), n=60, share=(0.0, 0.0)),
    line("hdmi_1", (39.2, -0.6, 1.7), (39.2, -20, 1.7), n=60, share=(0.0, 0.0)),
    line("ethernet", (88.6, 10.2, 1.0), (110, 10.2, 1.0), n=60, share=(0.0, 0.0)),
    line("usb_29", (88.6, 29.1, 1.0), (110, 29.1, 1.0), n=60, share=(0.0, 0.0)),
    line("usb_47", (88.6, 47, 1.0), (110, 47, 1.0), n=60, share=(0.0, 0.0)),
    # The flex cable's path, round the Base's edge (X = -1) on its connector's centre
    # line (Y = 29.89, Pimoroni's drawing) up to the Pi's: 2.5 mm of room past the
    # Base's edge, inside the case, and clear from the Base up past the Pi. Its width
    # isn't published, so only its centre line is checked.
    line("flex_room", (-1.1, 29.89, -6), (-3.6, 29.89, -6), n=30, share=(0.0, 0.0)),
    line("flex_cable", (-2.5, 29.89, -14), (-2.5, 29.89, 1), n=60, share=(0.0, 0.0)),
)
# A boss under each hole, under the Base: material round each hole's axis, 2 mm out,
# 2 mm under the lowest the Base's top could be with a 1.6 mm board under it.
PI5_SUPPORTS = tuple(
    ring(f"boss_{x}_{y}", (x, y, -17.2), 2.0, n=36, share=(0.5, 1.0)) for x, y in PI5_HOLES
)

CASES: dict[str, Case] = {
    c.name: c
    for c in (
        # Tier 6: tight features, one part.
        Case(
            "living-hinge",
            6,
            (
                Member(
                    "part",
                    bbox=((-32, 32), (-10, 10), (0, 3)),
                    volume=2 * 30 * 20 * 3 + 4 * 20 * 0.4,
                    # The web's top at 0.4 ± 0.05: in below, out above.
                    inside={
                        "web_at_least": (0, 0, 0.34),
                        "web_edge": (0, 9.9, 0.2),
                        "flap_-x": (-17, 0, 1.5),
                        "flap_+x": (17, 0, 1.5),
                        "flap_edge_-x": (-2.11, 0, 1.5),
                        "flap_edge_+x": (2.11, 0, 1.5),
                    },
                    outside={
                        "web_at_most": (0, 0, 0.46),
                        "gap": (0, 0, 1.5),
                        "gap_edge_-x": (-1.89, 0, 1.5),
                        "gap_edge_+x": (1.89, 0, 1.5),
                    },
                ),
            ),
        ),
        Case(
            "press-fit-pin",
            6,
            (
                Member(
                    "part",
                    bbox=((-2.55, 2.55), (-2.55, 2.55), (0, 16)),
                    tol=0.05,
                    volume=math.pi * 2.55**2 * 16
                    - 2 * math.pi * 0.5 * (2.55**2 - (2.55**2 + 2.55 * 2.05 + 2.05**2) / 3),
                    inside={"pin_at_least": (2.53, 0, 8), "top": (0, 0, 15.9)},
                    outside={
                        "pin_at_most": (2.57, 0, 8),
                        "chamfer_bottom": (2.4, 0, 0.05),
                        "chamfer_top": (0, 2.4, 15.95),
                    },
                    # A diametral interference of 0.08 to 0.12 mm over the block's
                    # depth, less the chamfer: about 6.0 to 9.1 mm³ of overlap.
                    gaps=(Gap("block", interference=(5.9, 9.2)),),
                ),
            ),
            mates={"block": BLOCK},
        ),
        Case(
            "snap-hook",
            6,
            (
                Member(
                    "part",
                    bbox=((-5, 6), (-4, 4), (0, 20)),
                    volume=10 * 8 * 4 + 1.6 * 8 * 16 + 0.5 * 1 * 3 * 8,
                    inside={
                        "base": (0, 0, 2),
                        "beam": (4.2, 0, 10),
                        "beam_at_least_-x": (3.45, 0, 10),
                        "beam_at_least_+x": (4.95, 0, 10),
                        "hook_tip": (5.9, 0, 17.05),
                        "ramp": (5.3, 0, 19),
                    },
                    outside={
                        "beam_at_most_-x": (3.35, 0, 10),
                        "beam_at_most_+x": (5.05, 0, 10),
                        "under_catch": (5.5, 0, 16.95),
                        "past_tip": (6.06, 0, 17.1),
                        "past_ramp": (5.5, 0, 19),
                        "beside_beam": (0, 0, 10),
                    },
                    gaps=(Gap("panel", distance=(0.05, 0.15)),),
                ),
            ),
            mates={"panel": LEDGE},
        ),
        Case(
            "dovetail-slider",
            6,
            (
                Member(
                    "part",
                    bbox=((-15, 15), (-12, 12), (5.2, 15)),
                    # The groove: the tongue's flanks offset 0.2 mm square to themselves.
                    volume=30 * (24 * 9.8 - (2 * 5.2954 + 2 * 7.2954) / 2 * 5),
                    # 0.05 mm square to a flank is 0.054 mm across it.
                    inside={
                        "flank_+y": (0, 6.355, 7.7),
                        "flank_-y": (0, -6.355, 7.7),
                        "over_groove": (0, 0, 10.26),
                        "bottom": (0, 10, 5.26),
                    },
                    outside={
                        "groove": (0, 0, 8),
                        "flank_clear_+y": (0, 6.24, 7.7),
                        "flank_clear_-y": (0, -6.24, 7.7),
                        "groove_top_clear": (0, 0, 10.14),
                        "bottom_clear": (0, 10, 5.14),
                    },
                    gaps=(Gap("rail", distance=(0.15, 0.25)),),
                ),
            ),
            mates={"rail": DOVETAIL},
        ),
        Case(
            "print-in-place-hinge",
            6,
            (
                Member(
                    "part",
                    solids=2,
                    bbox=((-25, 25), (-15, 15), (-3, 3)),
                    volume=VOLUMES["print-in-place-hinge"],
                    inside={
                        "pin_at_least": (1.44, 0, 0),
                        "pin_end": (0, -14.9, 0),
                        "bore_at_most": (0, 0, 1.86),
                        "knuckle_b": (0, 4.79, 2.5),
                        "knuckle_a": (0, 5.21, 2.5),
                        "plate_b": (3.36, 10, 0),
                        "plate_a": (-3.36, 0, 0),
                    },
                    outside={
                        "pin_at_most": (1.56, 0, 0),
                        "bore_at_least": (0, 0, 1.74),
                        "knuckle_ends": (0, 5.0, 2.5),
                        "knuckle_a_to_plate_b": (3.15, 10, 0),
                        "knuckle_b_to_plate_a": (-3.15, 0, 0),
                    },
                    own_gap=(0.25, 0.35),
                ),
            ),
        ),
        Case(
            "spur-gear",
            6,
            (
                Member(
                    "part",
                    bbox=((-16.5, 16.5), (-16.5, 16.5), (0, 8)),
                    volume=VOLUMES["spur-gear"],
                    inside={"bore_at_most": (0, 3.03, 4), "tooth_+x": (16.4, 0, 4)},
                    outside={
                        "bore_at_least": (0, 2.97, 4),
                        "gap_+x": (15, 15 * math.tan(math.pi / 20), 4),
                    },
                    # A tooth's share of a circle, the involute's within about 0.1 mm of
                    # tooth width (0.02 of the pitch): half at the pitch circle. A prime
                    # count of points, so they can't line up with the 20 teeth.
                    samples=(
                        ring("pitch", (0, 0, 4), 15, n=499, share=(0.48, 0.52), changes=(40, 40)),
                        ring(
                            "addendum",
                            (0, 0, 4),
                            15.5,
                            n=499,
                            share=(0.394, 0.434),
                            changes=(40, 40),
                        ),
                        ring("root", (0, 0, 4), 13.0, n=181, share=(0.99, 1.0)),
                        ring("past_tips", (0, 0, 4), 16.6, n=181, share=(0.0, 0.01)),
                    ),
                ),
            ),
        ),
        Case(
            "m8-bolt",
            6,
            (
                Member(
                    "part",
                    bbox=((-7.5056, 7.5056), (-6.5, 6.5), (-5.3, 20)),
                    # The head, and a shank between the roots' and the crests' cylinders.
                    volume_range=(
                        HEX_AREA * 5.3 + math.pi * 3.323**2 * 20,
                        HEX_AREA * 5.3 + math.pi * 4.0**2 * 20,
                    ),
                    inside={"flat_at_least": (0, 6.4, -2.6), "corner": (7.4, 0, -2.6)},
                    outside={"flat_at_most": (0, 6.6, -2.6), "past_corner": (7.6, 0, -2.6)},
                    samples=(
                        # Along the flanks: in and out at each half pitch, 12.8 pitches.
                        line(
                            "flanks", (3.6, 0, 2), (3.6, 0, 18), share=(0.3, 0.7), changes=(24, 28)
                        ),
                        line("roots", (0, 3.2, 2), (0, 3.2, 18), share=(0.99, 1.0)),
                        line("crests", (-3.88, 0, 2), (-3.88, 0, 18), share=(0.05, 0.5)),
                        line("past_crests", (0, -4.02, 2), (0, -4.02, 18), share=(0.0, 0.01)),
                        helix("right_hand", 3.6, 1.25, 3, 17),
                    ),
                ),
            ),
        ),
        # Tier 7: assemblies, each member its own STEP file, placed as assembled.
        Case(
            "pin-clevis",
            7,
            (
                Member(
                    "clevis",
                    bbox=((-8, 8), (-9, 9), (0, 26)),
                    volume=16 * 18 * 6 + 2 * 16 * 4 * 20 - 2 * math.pi * 3.15**2 * 4,
                    # The holes' radius 3.15 ± 0.025: in past it, out short of it.
                    inside={"base": (0, 0, 3), "cheek": (0, 7, 10), "hole_at_most": (3.19, -7, 18)},
                    outside={
                        "hole": (0, -7, 18),
                        "hole_at_least": (0, 7, 21.11),
                        "between_cheeks": (0, 0, 15),
                    },
                ),
                Member(
                    "tongue",
                    bbox=((-6, 6), (-4.6, 4.6), (10, 40)),
                    volume=12 * 9.2 * 30 - math.pi * 3.15**2 * 9.2,
                    inside={"bar": (0, 0, 30), "hole_at_most": (3.19, 0, 18)},
                    outside={"hole": (0, 0, 18), "hole_at_least": (0, 0, 21.11)},
                    gaps=(Gap("clevis", distance=(0.3, 0.5)),),
                ),
                Member(
                    "pin",
                    bbox=((-5, 5), (-12, 10), (13, 23)),
                    volume=math.pi * 3**2 * 20 + math.pi * 5**2 * 2,
                    inside={"pin_at_least": (2.97, 0, 18), "head": (4.9, -11, 18)},
                    outside={"pin_at_most": (0, 0, 21.03), "past_head": (0, -12.1, 18)},
                    gaps=(
                        Gap("clevis", distance=(0.1, 0.2)),
                        Gap("tongue", distance=(0.1, 0.2)),
                    ),
                ),
            ),
        ),
        Case(
            "shaft-bushing-collar",
            7,
            (
                Member(
                    "shaft",
                    bbox=((-4, 4), (-4, 4), (-10, 50)),
                    volume=math.pi * 4**2 * 60,
                    inside={"shaft_at_least": (3.97, 0, 20)},
                    outside={"shaft_at_most": (0, 4.03, 20)},
                    gaps=(
                        Gap("bushing", distance=(0.1, 0.2)),
                        Gap("collar", distance=(0.1, 0.2)),
                    ),
                ),
                Member(
                    "bushing",
                    bbox=((-9, 9), (-9, 9), (0, 12)),
                    volume=math.pi * (9**2 * 2 + 6**2 * 10 - 4.15**2 * 12),
                    inside={
                        "flange": (0, 8.9, 1),
                        "sleeve": (5.9, 0, 10),
                        "bore_at_most": (4.18, 0, 6),
                    },
                    outside={"bore_at_least": (4.12, 0, 6), "past_sleeve": (0, 8, 6)},
                ),
                Member(
                    "collar",
                    bbox=((-9, 9), (-9, 9), (12.3, 20.3)),
                    volume=math.pi * (9**2 - 4.15**2) * 8 - math.pi * 1.25**2 * (9 - 4.15),
                    inside={"ring": (0, 8.5, 16.3), "bore_at_most": (0, 4.18, 16.3)},
                    outside={"set_screw": (6.5, 0, 16.3), "bore_at_least": (0, -4.12, 16.3)},
                    gaps=(Gap("bushing", distance=(0.25, 0.35)),),
                ),
            ),
        ),
        Case(
            "drawer-cabinet",
            7,
            (
                Member(
                    "cabinet",
                    bbox=((-50, 50), (0, 80), (0, 60)),
                    volume=100 * 80 * 60 - 94 * 77 * 54,
                    inside={
                        "side": (48.5, 40, 30),
                        "back": (0, 78.5, 30),
                        "floor": (0, 40, 1.5),
                        "top": (0, 40, 58.5),
                    },
                    outside={"inside": (0, 40, 30), "open_front": (0, 0.5, 30)},
                ),
                Member(
                    "drawer",
                    bbox=((-50, 50), (-3.5, 76.5), (0.5, 59.5)),
                    volume=93 * 77 * 46.5 - 89 * 73 * 44.5 + 100 * 3 * 59 - math.pi * 10**2 * 5,
                    inside={"side": (45.5, 40, 30), "floor": (0, 40, 4.5), "front": (0, -2, 10)},
                    outside={
                        "inside": (0, 40, 30),
                        "finger_hole": (0, -2, 40),
                        "over_body": (0, 0, 52),
                    },
                    gaps=(Gap("cabinet", distance=(0.4, 0.6)),),
                ),
            ),
        ),
        Case(
            "gear-pair",
            7,
            (
                Member(
                    "plate",
                    bbox=((-12, 58), (-25, 25), (0, 14)),
                    volume=70 * 50 * 4 + 2 * math.pi * 2.5**2 * 10,
                    inside={"post_a_at_least": (2.47, 0, 10), "post_b_at_least": (30.2, 2.47, 10)},
                    outside={"post_a_at_most": (2.53, 0, 10), "post_b_at_most": (30.2, -2.53, 10)},
                ),
                Member(
                    "gear-a",
                    bbox=((-10.5, 10.5), (-10.5, 10.5), (4.5, 10.5)),
                    volume=VOLUMES["gear-a"],
                    inside={"bore_at_most": (0, 2.73, 7.5), "tooth_+x": (10.4, 0, 7.5)},
                    outside={"bore_at_least": (0, 2.67, 7.5)},
                    samples=(
                        ring("pitch", (0, 0, 7.5), 9, n=499, share=(0.48, 0.52), changes=(24, 24)),
                        ring("root", (0, 0, 7.5), 7.0, n=181, share=(0.99, 1.0)),
                    ),
                    gaps=(
                        Gap("gear-b", distance=(0.02, 0.3)),
                        Gap("plate", distance=(0.15, 0.25)),
                    ),
                ),
                Member(
                    "gear-b",
                    bbox=BOXES["gear-b"],
                    volume=VOLUMES["gear-b"],
                    inside={"bore_at_most": (30.2, 2.73, 7.5)},
                    outside={"bore_at_least": (30.2, 2.67, 7.5), "gap_-x": (30.2 - 22.4, 0, 7.5)},
                    samples=(
                        ring(
                            "pitch", (30.2, 0, 7.5), 21, n=499, share=(0.48, 0.52), changes=(56, 56)
                        ),
                        ring("root", (30.2, 0, 7.5), 19.0, n=181, share=(0.99, 1.0)),
                    ),
                    gaps=(Gap("plate", distance=(0.15, 0.25)),),
                ),
            ),
        ),
        Case(
            "bolt-nut",
            7,
            (
                Member(
                    "bolt",
                    bbox=((-7.5056, 7.5056), (-6.5, 6.5), (-5.3, 30)),
                    volume_range=(
                        HEX_AREA * 5.3 + math.pi * 3.323**2 * 30,
                        HEX_AREA * 5.3 + math.pi * 4.0**2 * 30,
                    ),
                    inside={"flat_at_least": (0, 6.4, -2.6)},
                    outside={"flat_at_most": (0, 6.6, -2.6)},
                    samples=(
                        line(
                            "flanks", (3.6, 0, 2), (3.6, 0, 28), share=(0.3, 0.7), changes=(39, 44)
                        ),
                        line("roots", (0, 3.2, 2), (0, 3.2, 28), share=(0.99, 1.0)),
                        line("past_crests", (0, -4.02, 2), (0, -4.02, 28), share=(0.0, 0.01)),
                        helix("right_hand", 3.6, 1.25, 3, 27),
                    ),
                ),
                Member(
                    "nut",
                    bbox=((-7.5056, 7.5056), (-6.5, 6.5), (10, 16.5)),
                    # The hexagon, less a bore between the thread's grown roots and crests.
                    volume_range=(
                        HEX_AREA * 6.5 - math.pi * 4.15**2 * 6.5,
                        HEX_AREA * 6.5 - math.pi * 3.473**2 * 6.5,
                    ),
                    inside={"flat_at_least": (0, 6.4, 13)},
                    outside={"flat_at_most": (0, 6.6, 13)},
                    samples=(
                        line(
                            "flanks",
                            (3.6, 0, 10.5),
                            (3.6, 0, 16),
                            share=(0.3, 0.7),
                            changes=(7, 11),
                        ),
                        line("bore", (0, 3.4, 10.5), (0, 3.4, 16), share=(0.0, 0.01)),
                        line("past_roots", (0, -4.25, 10.5), (0, -4.25, 16), share=(0.99, 1.0)),
                        helix("right_hand", 3.8, 1.25, 11, 15.5, n=120),
                    ),
                    gaps=(Gap("bolt", distance=(0.05, 0.2)),),
                ),
            ),
        ),
        Case(
            "snap-enclosure",
            7,
            (
                Member(
                    "box",
                    bbox=((-30, 30), (-20, 20), (0, 30)),
                    volume=60 * 40 * 30 - 56 * 36 * 28 - 2 * 2 * 12 * 4,
                    inside={
                        "over_window": (29, 0, 26),
                        "under_window": (29, 0, 20),
                        "side": (0, 19, 15),
                        "floor": (0, 0, 1),
                    },
                    outside={
                        "window_+x": (29, 0, 23),
                        "window_-x": (-29, 0, 23),
                        "inside": (0, 0, 15),
                    },
                ),
                Member(
                    "lid",
                    bbox=((-31.8, 31.8), (-20, 20), (20, 32)),
                    volume=63.6 * 40 * 2 + 2 * 1.6 * 10 * 10 + 2 * 0.5 * 1 * 3 * 10,
                    # Each hook in its window's wall, under the window's top: it holds.
                    inside={
                        "hook_+x_holds": (29.6, 0, 24.75),
                        "hook_-x_holds": (-29.6, 0, 24.75),
                        "arm": (31, 0, 25),
                        "plate": (0, 0, 31),
                    },
                    outside={
                        "over_hook": (29.6, 0, 24.85),
                        "arm_clear": (30.1, 0, 27),
                        "ramp": (29.9, 0, 22.2),
                    },
                    gaps=(Gap("box"),),
                ),
            ),
        ),
        Case(
            "caster-wheel",
            7,
            (
                Member(
                    "axle",
                    bbox=((-2.5, 2.5), (-14, 14), (-2.5, 2.5)),
                    volume=math.pi * 2.5**2 * 28,
                    inside={"axle_at_least": (2.47, 0, 0)},
                    outside={"axle_at_most": (0, 0, 2.53)},
                    gaps=tuple(
                        Gap(o, distance=(0.1, 0.2))
                        for o in ("wheel", "spacer-a", "spacer-b", "fork")
                    ),
                ),
                Member(
                    "wheel",
                    bbox=((-20, 20), (-6, 6), (-20, 20)),
                    volume=math.pi * (20**2 - 2.65**2) * 12,
                    inside={"rim": (0, 0, 19.9), "bore_at_most": (2.68, 0, 0)},
                    outside={"bore_at_least": (2.62, 0, 0)},
                    gaps=(
                        Gap("spacer-a", distance=(0.25, 0.35)),
                        Gap("spacer-b", distance=(0.25, 0.35)),
                    ),
                ),
                *(
                    Member(
                        name,
                        bbox=((-4.5, 4.5), (y0, y1), (-4.5, 4.5)),
                        volume=math.pi * (4.5**2 - 2.65**2) * 2.7,
                        inside={
                            "tube": (0, (y0 + y1) / 2, 4.4),
                            "bore_at_most": (0, (y0 + y1) / 2, 2.68),
                        },
                        outside={"bore_at_least": (0, (y0 + y1) / 2, 2.62)},
                    )
                    for name, y0, y1 in (("spacer-a", -9, -6.3), ("spacer-b", 6.3, 9))
                ),
                Member(
                    "fork",
                    bbox=((-12, 12), (-13.3, 13.3), (-8, 30)),
                    volume=2 * 16 * 4 * 34 + 24 * 26.6 * 4 - 2 * math.pi * 2.65**2 * 4,
                    inside={"arm": (0, 11, 20), "top": (0, 0, 28), "hole_at_most": (2.68, 11.3, 0)},
                    outside={"hole_at_least": (0, 11.3, 2.62), "between_arms": (0, 0, 10)},
                    gaps=(
                        Gap("spacer-a", distance=(0.25, 0.35)),
                        Gap("spacer-b", distance=(0.25, 0.35)),
                    ),
                ),
            ),
        ),
        # Tier 8: in a person's words, the dimensions the model's to choose.
        Case(
            "shelf-bracket",
            8,
            (
                Member(
                    "part",
                    within=((0, 150), (-30, 30), (-200, 0)),
                    samples=(
                        # Its top carries the shelf from the wall to 100 mm out.
                        line("carries_shelf", (2, 0, -0.3), (100, 0, -0.3), share=(0.99, 1.0)),
                        line("on_the_wall", (0.3, 0, -1), (0.3, 0, -40), share=(0.8, 1.0)),
                    ),
                    holes=(Holes("screws", "x", (2.1, 2.6), 2),),
                    # 2 kg on two brackets: 9.81 N on each, at the shelf's middle, 75 mm out.
                    load=Load("shelf", "x", 20, force_n=1 * G, arm_mm=75 - 20),
                ),
            ),
        ),
        Case(
            "tube-clip",
            8,
            (
                Member(
                    "part",
                    within=((-30, 30), (-30, 30), (-45, 0)),
                    samples=(
                        # It wraps more than half the tube, so it snaps on, and leaves an
                        # opening; its bore takes the tube and grips it.
                        ring("wraps", (0, 0, -20), 10.6, axis="x", n=181, share=(0.55, 0.95)),
                        ring("takes_tube", (0, 0, -20), 9.95, axis="x", n=181, share=(0.0, 0.01)),
                        ring("grips", (0, 0, -20), 10.4, axis="x", n=181, share=(0.5, 1.0)),
                        line("on_desk", (0, -15, -0.3), (0, 15, -0.3), share=(0.5, 1.0)),
                    ),
                    holes=(Holes("screws", "z", (2.1, 2.6), 1),),
                ),
            ),
        ),
        Case(
            "d-shaft-knob",
            8,
            (
                Member(
                    "part",
                    within=((-25, 25), (-25, 25), (0.5, 40)),
                    spans=((20, 50), (20, 50), (10, 40)),
                    # The bore keys on the flat (X = 1.5), from Z = 4 to the shaft's tip.
                    inside={
                        "keys_flat": (1.75, 0, 8),
                        "keys_flat_low": (1.75, 0, 4.5),
                        "keys_flat_high": (1.75, 0, 11.5),
                        "round_snug": (0, 3.2, 8),
                    },
                    outside={"bore": (0, 0, 8)},
                    # Snug: at most 0.15 mm off the shaft, or pressed on by a little.
                    gaps=(Gap("shaft", interference=(0.0, 1.0), distance=(0.0, 0.15)),),
                ),
            ),
            mates={"shaft": D_SHAFT},
        ),
        Case(
            "wall-hook",
            8,
            (
                Member(
                    "part",
                    within=((0, 100), (-40, 40), (-60, 60)),
                    spans=(None, (40, 80), None),
                    holes=(Holes("screws", "x", (2.1, 2.6), 2),),
                    # 5 kg hung at the hook's far end, the worst place it could hang.
                    load=Load("bag", "x", 8, force_n=5 * G),
                ),
            ),
        ),
        Case(
            "cable-comb",
            8,
            (
                Member(
                    "part",
                    within=((-30, 30), (-60, 60), (0, 40)),
                    spans=(None, None, (12, 40)),
                    samples=(
                        # Six slots across the cables' centres: in, then out and in for
                        # each, then out, 14 changes; each slot 5 to 6 mm, snug.
                        line(
                            "cables",
                            (0, -60, 10),
                            (0, 60, 10),
                            n=601,
                            changes=(14, 14),
                            gaps=(5.0, 6.0),
                        ),
                        line("open_top", (0, -60, 14), (0, 60, 14), n=601, changes=(14, 14)),
                    ),
                ),
            ),
        ),
        Case(
            "spool-holder",
            8,
            (
                Member(
                    "part",
                    within=((0, 150), (-60, 60), (-60, 60)),
                    samples=(
                        # Clear of the 53 mm hole by 0.2 mm at least, under the spool's
                        # whole width.
                        ring("clears_hub", (40, 0, 0), 26.3, axis="x", n=181, share=(0.0, 0.01)),
                        line("carries_width", (8, 0, 0), (75, 0, 0), share=(0.99, 1.0)),
                    ),
                    holes=(Holes("screws", "x", (2.1, 2.6), 2),),
                    load=Load("spool", "x", 8, force_n=1 * G),
                ),
            ),
        ),
        # The Sponsor's case (mqucifer/model-performance#16, 2026-10-25): a case for a
        # Raspberry Pi 5 with a Pimoroni NVMe Base Duo under it. Its keep-outs and port
        # axes are only what the boards' drawings publish (`cad_eval/README.md`).
        Case(
            "pi5-nvme-case",
            8,
            tuple(
                Member(
                    name,
                    within=((-20, 110), (-20, 80), (-50, 50)),
                    samples=PI5_PORTS + (supports if name == "base" else ()),
                    gaps=(Gap("pi5"), Gap("nvme_base"), *((Gap("base"),) if name == "lid" else ())),
                    vents=(
                        Vents("over_the_pi", ((5, 80), (5, 51)), area=300.0)
                        if name == "lid"
                        else None
                    ),
                )
                for name, supports in (("base", PI5_SUPPORTS), ("lid", ()))
            ),
            mates={"pi5": PI5_KEEP_OUT, "nvme_base": NVME_BASE_KEEP_OUT},
        ),
    )
}
# The first run's cases (mqucifer/model-performance#16): one of each kind, the hardest
# tight feature and assembly, and the Sponsor's case, easiest first.
FIRST = ("pin-clevis", "shelf-bracket", "m8-bolt", "caster-wheel", "pi5-nvme-case")
