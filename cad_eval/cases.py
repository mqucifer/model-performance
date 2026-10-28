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
    spacing: float = 0.0  # between points along a line, or round a ring, mm
    # Round a ring, the range of each run of points in the material, in mm of arc:
    # each tooth's own width, where the share holds only their mean (round 2 of #41).
    runs: Span | None = None
    # For a line, the range of the mean distance in mm between one rise into the
    # material and the next: a thread's pitch, measured (the second review of #41).
    period: Span | None = None


def ring(
    name: str,
    centre: Point,
    radius: float,
    *,
    axis: str = "z",
    n: int = 360,
    share: Span = (0.0, 1.0),
    changes: tuple[int, int] | None = None,
    runs: Span | None = None,
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
    spacing = 2 * math.pi * radius / n
    return Sample(name, tuple(points), share, changes, closed=True, spacing=spacing, runs=runs)


def line(
    name: str,
    start: Point,
    end: Point,
    *,
    n: int = 200,
    share: Span = (0.0, 1.0),
    changes: tuple[int, int] | None = None,
    gaps: Span | None = None,
    period: Span | None = None,
) -> Sample:
    """`n` points from `start` to `end`, both included."""
    points = tuple(
        tuple(round(a + (b - a) * k / (n - 1), 3) for a, b in zip(start, end, strict=True))
        for k in range(n)
    )
    spacing = math.dist(start, end) / (n - 1)
    return Sample(name, points, share, changes, gaps=gaps, spacing=spacing, period=period)  # type: ignore[arg-type]


def grid(
    name: str,
    x: float,
    ys: tuple[float, float],
    zs: tuple[float, float],
    *,
    step: float = 1.0,
    share: Span = (0.0, 1.0),
) -> Sample:
    """Points over a rectangle in the plane X = `x`, `step` apart: an area's share of
    material, where a line would be cut by any hole on it."""
    ny, nz = int((ys[1] - ys[0]) / step) + 1, int((zs[1] - zs[0]) / step) + 1
    points = tuple(
        (x, round(ys[0] + i * step, 3), round(zs[0] + j * step, 3))
        for i in range(ny)
        for j in range(nz)
    )
    return Sample(name, points, share)


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
class Cylinder:
    """A cylindrical face the spec states, measured off the part's own faces: a hole's
    or an outer one's (`kind`), along `axis`, through `through`. Its radius within
    `radius`, and its axis within `offset` of where it should be: a diameter held to its
    own tolerance and its place to its own (the second review of #41: one probe held
    both, and failed a correct bore shifted 0.04 mm)."""

    name: str
    axis: str
    through: Point
    radius: Span
    kind: str = "hole"
    offset: float = 0.1


@dataclass(frozen=True)
class Slope:
    """How fast the material's share falls between two of a member's samples: `high`'s
    share less `low`'s, within `span`. A thread's flank angle, which no single radius
    can hold: a profile 0.1 mm bigger or smaller shifts both shares alike, and a
    different angle changes their difference (the review of #41: an 85° V passed)."""

    name: str
    high: str
    low: str
    span: Span


@dataclass(frozen=True)
class SectionSpan:
    """The material's extent across the plane `axis` = `at`: in `across`, within `span`.
    A feature's own width, where a part's overall box would count a wall plate too."""

    name: str
    axis: str
    at: float
    across: str
    span: Span
    # The cut only within this span along this axis, when the plane cuts two features
    # and one is held: a clevis's cheek, of the two (round 2 of #41's audit).
    clip: tuple[str, Span] | None = None
    # Read as this extent less another section span's, by name: a hook's overhang, its
    # tip's section less the beam's own thickness, wherever its catch sits.
    less: str | None = None


@dataclass(frozen=True)
class RegionGap:
    """The closest distance to `other` (a member, a mate, or "self" for the member's own
    solids) of only the material in `box`: one face pair's clearance, where a `Gap`
    holds only the closest of all (round 2 of #41's audit: "0.3 mm everywhere")."""

    name: str
    other: str
    box: tuple[Span, Span, Span]
    distance: Span


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
    section_spans: tuple[SectionSpan, ...] = ()
    slopes: tuple[Slope, ...] = ()
    cylinders: tuple[Cylinder, ...] = ()
    region_gaps: tuple[RegionGap, ...] = ()
    # Where the part's middle must be, by axis, when its size is the model's to choose
    # ("centred on Y = 0"): its box's centre within `tol` of it (round 2 of #41's audit).
    centred: tuple[tuple[str, float], ...] = ()

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
# A boss under each hole, under the Base: material round each hole's axis, 2.5 mm out
# (#40 V2: at 2 mm a heat-set insert's hole, up to 4.5 mm across, failed it),
# 2 mm under the lowest the Base's top could be with a 1.6 mm board under it.
PI5_SUPPORTS = tuple(
    ring(f"boss_{x}_{y}", (x, y, -17.2), 2.5, n=36, share=(0.5, 1.0)) for x, y in PI5_HOLES
)


def mirrored(points: dict[str, Point]) -> dict[str, Point]:
    """Probes on the +X side, and the same on the -X side, by name."""
    found: dict[str, Point] = {}
    for name, (x, y, z) in points.items():
        found[f"{name}_+x"] = (x, y, z)
        found[f"{name}_-x"] = (-x, y, z)
    return found


# press-fit-pin's 0.5 mm by 45° chamfers, at their stated ±0.1 (#40: only a chamfer's
# existence was held): at a height h over an end the chamfer's face is at r = 2.55 - c
# + h, so at h = 0.1 and 0.3, between 2.05 and 2.25, and between 2.25 and 2.45; each probe
# on that band's edge (#40 V2: 0.02 past it, so ±0.12). And each leg on its own, so the 45°
# is held as the legs' ±0.1 allow, 34° to 56° (#40 V2: the two heights held 31° to 54°,
# and a round passed): the radial leg 0.01 over the end, where the face is at r = 2.56 - c,
# and the axial one at r = 2.52, where it is at h = c - 0.03.
CHAMFER_IN = {
    "chamfer_bottom_low": (2.05, 0, 0.1),
    "chamfer_bottom_high": (2.25, 0, 0.3),
    "chamfer_top_low": (0, 2.05, 15.9),
    "chamfer_top_high": (0, 2.25, 15.7),
    "chamfer_bottom_radial": (1.96, 0, 0.01),
    "chamfer_bottom_axial": (2.52, 0, 0.57),
    "chamfer_top_radial": (0, 1.96, 15.99),
    "chamfer_top_axial": (0, 2.52, 15.43),
}
CHAMFER_OUT = {
    "chamfer_bottom_low_out": (2.25, 0, 0.1),
    "chamfer_bottom_high_out": (2.45, 0, 0.3),
    "chamfer_top_low_out": (0, 2.25, 15.9),
    "chamfer_top_high_out": (0, 2.45, 15.7),
    "chamfer_bottom_radial_out": (2.16, 0, 0.01),
    "chamfer_bottom_axial_out": (2.52, 0, 0.37),
    "chamfer_top_radial_out": (0, 2.16, 15.99),
    "chamfer_top_axial_out": (0, 2.52, 15.63),
}
# snap-enclosure, held on both ends to its stated ±0.05 (arms, hooks) and ±0.1 (the rest)
# (#40: most were held to 0.6-1.1 mm, and only on +X). Each probe sits its tolerance
# inside or outside its face, which is at its nominal place: 0.1 on the box, 0.05 on the
# arms and hooks (#40 round 2: they sat 0.12 and 0.07 off).
SNAP_BOX_IN = {
    **mirrored(
        {
            "over_window": (29, 0, 25.1),
            "under_window": (29, 0, 20.9),
            "past_window_+y": (29, 6.1, 23),
            "past_window_-y": (29, -6.1, 23),
            "end_wall": (28.1, 10, 15),
        }
    ),
    "side_+y": (0, 18.1, 15),
    "side_-y": (0, -18.1, 15),
    "floor": (0, 0, 1.9),
}
SNAP_BOX_OUT = {
    **mirrored(
        {
            "window": (29, 0, 23),
            "window_top": (29, 0, 24.9),
            "window_bottom": (29, 0, 21.1),
            "window_+y_edge": (29, 5.9, 23),
            "window_-y_edge": (29, -5.9, 23),
            "end_wall_inside": (27.9, 10, 15),
        }
    ),
    "side_+y_inside": (0, 17.9, 15),
    "side_-y_inside": (0, -17.9, 15),
    "over_floor": (0, 0, 2.1),
    "inside": (0, 0, 15),
}
SNAP_LID_IN = {
    **mirrored(
        {
            "arm": (31, 0, 25),
            "arm_inner_face": (30.25, 0, 27),
            "arm_outer_face": (31.75, 0, 27),
            "arm_+y": (31, 4.95, 27),
            "arm_-y": (31, -4.95, 27),
            "arm_bottom": (31, 0, 20.05),
            # Up to the plate's underside, Z = 30.
            "arm_top": (31, 0, 29.95),
            "hook_holds": (29.6, 0, 24.75),
            # At Z = 24.7 a hook d deep has its ramp's face at 30.2 - 0.9667·d: for d of
            # 0.95 to 1.05, 29.185 to 29.282.
            "hook_tip": (29.281, 0, 24.7),
            # The ramp's face at Z = 23.3 is at 29.7, and at Z = 22.3, near its foot, at
            # 30.033: each ±0.05.
            "hook_ramp": (29.75, 0, 23.3),
            "ramp_foot": (30.083, 0, 22.3),
        }
    ),
    "plate": (0, 0, 31),
    # The plate's underside, Z = 30, at ±0.1.
    "plate_underside": (0, 0, 30.1),
}
SNAP_LID_OUT = {
    **mirrored(
        {
            "arm_clear": (30.15, 0, 27),
            "past_arm": (31.85, 0, 27),
            "past_arm_+y": (31, 5.05, 27),
            "past_arm_-y": (31, -5.05, 27),
            "under_arm": (31, 0, 19.95),
            "over_hook": (29.6, 0, 24.85),
            "past_hook": (29.186, 0, 24.7),
            "past_ramp": (29.65, 0, 23.3),
            "past_ramp_foot": (29.984, 0, 22.3),
        }
    ),
    "under_plate": (0, 0, 29.9),
}

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
                    # Every stated tolerance at its limit at once moves it 4.2% (#40 V2).
                    volume_rel=0.045,
                    # The web's top at 0.4 ± 0.05: in below, out above, each on the band's
                    # edge (#40 V2: 0.01 past it, so ±0.06).
                    inside={
                        "web_at_least": (0, 0, 0.35),
                        # The web along the flaps' whole 20 mm: both its ends (#40 V2: +Y only).
                        "web_edge": (0, 9.9, 0.2),
                        "web_edge_-y": (0, -9.9, 0.2),
                        "flap_-x": (-17, 0, 1.5),
                        "flap_+x": (17, 0, 1.5),
                        # The flaps' inner ends, X = ±2, at ±0.1 (#40 V2: 0.11).
                        "flap_edge_-x": (-2.1, 0, 1.5),
                        "flap_edge_+x": (2.1, 0, 1.5),
                    },
                    outside={
                        "web_at_most": (0, 0, 0.45),
                        "gap": (0, 0, 1.5),
                        "gap_edge_-x": (-1.9, 0, 1.5),
                        "gap_edge_+x": (1.9, 0, 1.5),
                    },
                    # The web's 0.4 thickness at its ±0.05, so with its top it's flush, and its
                    # 20 mm width at ±0.1, off the plane X = 0, which cuts the web alone (#40
                    # V2: its bottom had no check, so a web from Z = 0.19 to 0.45 passed).
                    section_spans=(
                        SectionSpan("web_thickness", "x", 0, "z", (0.35, 0.45)),
                        SectionSpan("web_width", "x", 0, "y", (19.9, 20.1)),
                    ),
                    # Each flap's 30 mm and the 4 mm gap, ±0.1, as sizes (#40 V2: only their
                    # ends were held, so the sizes to ±0.2): points 0.01 apart over 0.4 mm
                    # about each end, half in the material at the size; 0.1 is 10 of 80.
                    samples=(
                        Sample(
                            "flap_-x",
                            line("", (-32.195, 0, 1.5), (-31.805, 0, 1.5), n=40).points
                            + line("", (-2.195, 0, 1.5), (-1.805, 0, 1.5), n=40).points,
                            (0.375, 0.625),
                        ),
                        Sample(
                            "flap_+x",
                            line("", (1.805, 0, 1.5), (2.195, 0, 1.5), n=40).points
                            + line("", (31.805, 0, 1.5), (32.195, 0, 1.5), n=40).points,
                            (0.375, 0.625),
                        ),
                        Sample(
                            "gap",
                            line("", (-2.195, 0, 1.5), (-1.805, 0, 1.5), n=40).points
                            + line("", (1.805, 0, 1.5), (2.195, 0, 1.5), n=40).points,
                            (0.375, 0.625),
                        ),
                    ),
                ),
            ),
        ),
        Case(
            "press-fit-pin",
            6,
            (
                Member(
                    "part",
                    # The length at its stated ±0.1; the diameter's ±0.02 is the probes' and
                    # the press's (#40: a 0.05 box tolerance failed a 15.92 mm pin).
                    bbox=((-2.55, 2.55), (-2.55, 2.55), (0, 16)),
                    volume=math.pi * 2.55**2 * 16
                    - 2 * math.pi * 0.5 * (2.55**2 - (2.55**2 + 2.55 * 2.05 + 2.05**2) / 3),
                    inside={"top": (0, 0, 15.9), **CHAMFER_IN},
                    # Its 5.10 mm at ±0.02, on the Z axis at ±0.1.
                    cylinders=(Cylinder("pin", "z", (0, 0, 8), (2.54, 2.56), kind="outer"),),
                    outside={
                        "chamfer_bottom": (2.4, 0, 0.05),
                        "chamfer_top": (0, 2.4, 15.95),
                        **CHAMFER_OUT,
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
                    volume_rel=0.055,  # every stated tolerance at its limit (#40 V2)
                    inside={
                        "base": (0, 0, 2),
                        # The base's +X end, X = 5, ±0.1, at its own height (#40 V2).
                        "base_end": (4.9, 0, 2),
                        "beam": (4.2, 0, 10),
                        "beam_at_least_-x": (3.45, 0, 10),
                        "beam_at_least_+x": (4.95, 0, 10),
                        # The catch at most 17.05: its gap to the ledge at most 0.15, inside
                        # its ±0.1 (`under_catch` holds it from below, at 16.95).
                        "catch_at_most": (5.5, 0, 17.05),
                        # The ramp, at 5.333 at Z = 19, ±0.1 (#40 V2: -0.03/+0.17).
                        "ramp": (5.234, 0, 19),
                    },
                    outside={
                        "past_base_end": (5.1, 0, 2),
                        "beam_at_most_-x": (3.35, 0, 10),
                        "beam_at_most_+x": (5.05, 0, 10),
                        "under_catch": (5.5, 0, 16.95),
                        "past_tip": (6.06, 0, 17.1),
                        "past_ramp": (5.433, 0, 19),
                        "beside_beam": (0, 0, 10),
                    },
                    gaps=(Gap("panel", distance=(0.05, 0.15)),),
                    # The beam's 1.6 thickness at its ±0.05 and its 8 mm width at ±0.1, off
                    # the plane Z = 10, which cuts the beam alone (#40 V2: each face was held
                    # to ±0.05, so the 1.6 to ±0.1, and the width not at all).
                    section_spans=(
                        SectionSpan("beam_thickness", "z", 10, "x", (1.55, 1.65)),
                        SectionSpan("beam_width", "z", 10, "y", (7.9, 8.1)),
                        # The hook's overhang, 1.0 ± 0.05, wherever its catch sits (16.95 to
                        # 17.05, by its gap to the ledge): the section at Y = 0 between Z =
                        # 16.9 and 17.2 runs from the beam's back to the tip, less the beam's
                        # thickness. A probe at one height failed a correct catch at 17.02 or
                        # passed a short overhang, as the 1-in-3 ramp turns in (round 2).
                        SectionSpan(
                            "overhang",
                            "y",
                            0,
                            "x",
                            (0.95, 1.05),
                            clip=("z", (16.9, 17.2)),
                            less="beam_thickness",
                        ),
                    ),
                    # Sizes and places by points 0.01 apart over 0.4 mm about a face: the
                    # share in the material is where the face is (#40 V2).
                    samples=(
                        # The base's 10 mm along X and 4 mm tall, ±0.1: about both ends,
                        # half in at the size, and 0.1 is 10 of 80 points.
                        Sample(
                            "base_length",
                            line("", (-5.195, 0, 2), (-4.805, 0, 2), n=40).points
                            + line("", (4.805, 0, 2), (5.195, 0, 2), n=40).points,
                            (0.375, 0.625),
                        ),
                        Sample(
                            "base_height",
                            line("", (0, 0, -0.195), (0, 0, 0.195), n=40).points
                            + line("", (0, 0, 3.805), (0, 0, 4.195), n=40).points,
                            (0.375, 0.625),
                        ),
                        # The base's top beside the beam, Z = 4, and the beam's, Z = 20, each
                        # ±0.1 (10 of 40 points); the beam's face, X = 5 ±0.05; and the hook's
                        # The beam's face, X = 5 ±0.05.
                        line(
                            "base_top", (-2.5, 0, 3.805), (-2.5, 0, 4.195), n=40, share=(0.25, 0.75)
                        ),
                        line(
                            "beam_top", (4.2, 0, 19.805), (4.2, 0, 20.195), n=40, share=(0.25, 0.75)
                        ),
                        line(
                            "beam_face", (4.805, 0, 10), (5.195, 0, 10), n=40, share=(0.375, 0.625)
                        ),
                    ),
                    slopes=(
                        # The beam's 16 mm above the base, ±0.1: its top's share less the
                        # base top's, 0.1 a share of 0.25.
                        Slope("beam_height", "beam_top", "base_top", (-0.25, 0.25)),
                    ),
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
                    volume_rel=0.035,  # every stated tolerance at its limit (#40 V2)
                    # 0.05 mm square to a flank is 0.054 mm across it. Each probe on the
                    # clearance's 0.15 or 0.25 (#40 V2: 0.255 and 0.26 were held), each flank
                    # at three heights, so its lean is held, and the groove's top at three
                    # places along X: the most "on every face" where it's probed.
                    inside={
                        "flank_+y": (0, 6.349, 7.7),
                        "flank_-y": (0, -6.349, 7.7),
                        "flank_low_+y": (0, 5.509, 5.6),
                        "flank_low_-y": (0, -5.509, 5.6),
                        "flank_high_+y": (0, 7.189, 9.8),
                        "flank_high_-y": (0, -7.189, 9.8),
                        "over_groove": (0, 0, 10.25),
                        "over_groove_-x": (-14, 0, 10.25),
                        "over_groove_+x": (14, 0, 10.25),
                        "bottom": (0, 10, 5.25),
                    },
                    outside={
                        "groove": (0, 0, 8),
                        "flank_clear_+y": (0, 6.242, 7.7),
                        "flank_clear_-y": (0, -6.242, 7.7),
                        "flank_low_clear_+y": (0, 5.402, 5.6),
                        "flank_low_clear_-y": (0, -5.402, 5.6),
                        "flank_high_clear_+y": (0, 7.082, 9.8),
                        "flank_high_clear_-y": (0, -7.082, 9.8),
                        "groove_top_clear": (0, 0, 10.15),
                        "groove_top_clear_-x": (-14, 0, 10.15),
                        "groove_top_clear_+x": (14, 0, 10.15),
                        "bottom_clear": (0, 10, 5.15),
                    },
                    gaps=(Gap("rail", distance=(0.15, 0.25)),),
                    # The clearance 0.15 to 0.25 "on every face": each face pair's own, in a
                    # box that holds that pair alone, the whole block's length (#40 round 3:
                    # gap.rail.distance held only the closest face's). The flanks' boxes stop
                    # short of the base and the tongue's top, the top's within the tongue's
                    # corners, and the base's outside the tongue.
                    region_gaps=(
                        RegionGap(
                            "flank_+y", "rail", ((-15, 15), (5.5, 7.5), (5.6, 9.6)), (0.15, 0.25)
                        ),
                        RegionGap(
                            "flank_-y", "rail", ((-15, 15), (-7.5, -5.5), (5.6, 9.6)), (0.15, 0.25)
                        ),
                        RegionGap("top", "rail", ((-15, 15), (-6.5, 6.5), (9, 11)), (0.15, 0.25)),
                        RegionGap(
                            "base_+y", "rail", ((-15, 15), (7.5, 10.5), (4, 6.5)), (0.15, 0.25)
                        ),
                        RegionGap(
                            "base_-y", "rail", ((-15, 15), (-10.5, -7.5), (4, 6.5)), (0.15, 0.25)
                        ),
                    ),
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
                    # The bridges' height isn't stated (knuckle-tall ones add 2.1%), and
                    # every stated tolerance at its limit is about 4.3% more (#40 V2).
                    volume_rel=0.065,
                    inside={
                        "pin_end": (0, -14.9, 0),
                        # The knuckles' facing ends and the plates' inner edges, each at its
                        # ±0.1 (round 2: 0.06 inside, a valid end 0.08 off, its clearance
                        # kept by the other's, failed).
                        "knuckle_b": (0, 4.75, 2.5),
                        "knuckle_a": (0, 5.25, 2.5),
                        "plate_b": (3.4, 10, 0),
                        "plate_a": (-3.4, 0, 0),
                        # Each face at ±0.1 the box doesn't hold (#40 round 2): the plates'
                        # faces at Z = ±1.5 and their ends at Y = ±15 (+X is plate B's, -X
                        # A's); the pin's and knuckle A's outer ends at Y = ±15; the -Y
                        # knuckles' ends (B's at -4.85, A's at -5.15); and each knuckle out to
                        # r = 2.9, so the knuckles' cylinder holds it.
                        **mirrored(
                            {
                                "plate_top": (15, 10, 1.4),
                                "plate_bottom": (15, 10, -1.4),
                                "plate_-y": (15, -14.9, 0),
                                "plate_+y": (15, 14.9, 0),
                            }
                        ),
                        "pin_end_+y": (0, 14.9, 0),
                        "knuckle_a_end_-y": (0, -14.9, 2.5),
                        "knuckle_a_end_+y": (0, 14.9, 2.5),
                        "knuckle_b_-y": (0, -4.75, 2.5),
                        "knuckle_a_-y": (0, -5.25, 2.5),
                        "knuckle_a_-y_round": (0, -10, 2.9),
                        "knuckle_b_round": (0, 0, 2.9),
                        "knuckle_a_+y_round": (0, 10, 2.9),
                    },
                    outside={
                        "knuckle_ends": (0, 5.0, 2.5),
                        "knuckle_a_to_plate_b": (3.15, 10, 0),
                        "knuckle_b_to_plate_a": (-3.15, 0, 0),
                        # 0.1 past each knuckle's end and short of each plate's inner edge,
                        # and over and under each plate (#40 round 2).
                        "past_knuckle_b": (0, 4.95, 2.5),
                        "short_of_knuckle_a": (0, 5.05, 2.5),
                        "past_knuckle_b_-y": (0, -4.95, 2.5),
                        "short_of_knuckle_a_-y": (0, -5.05, 2.5),
                        "short_of_plate_b": (3.2, 10, 0),
                        "short_of_plate_a": (-3.2, 0, 0),
                        **mirrored({"over_plate": (15, 10, 1.6), "under_plate": (15, 10, -1.6)}),
                    },
                    # Each bridge over its knuckle's length, across the 0.3 between the
                    # knuckle and its plate (#40 round 2).
                    samples=tuple(
                        line(name, (x, y0, 0), (x, y1, 0), n=50, share=(0.99, 1.0))
                        for name, x, y0, y1 in (
                            ("bridge_a_-y", -3.15, -14.9, -5.3),
                            ("bridge_a_+y", -3.15, 5.3, 14.9),
                            ("bridge_b", 3.15, -4.7, 4.7),
                        )
                    ),
                    # Each plate's own 3 mm at ±0.1, where nothing else is: the box's Z is
                    # the knuckles' (#40 round 2).
                    section_spans=(
                        SectionSpan("plate_a", "x", -15, "z", (2.9, 3.1)),
                        SectionSpan("plate_b", "x", 15, "z", (2.9, 3.1)),
                    ),
                    own_gap=(0.25, 0.35),
                    # The clearance, 0.25 to 0.35 "everywhere", at each place the leaves meet:
                    # the closest distance between the two solids in a box round each, which
                    # holds that face pair and no other (round 3 of #41's audit).
                    region_gaps=tuple(
                        RegionGap(name, "self", box, (0.25, 0.35))
                        for name, box in (
                            # The pin in knuckle B's bore, inside r = 2.2.
                            ("pin", ((-2.2, 2.2), (-4, 4), (-2.2, 2.2))),
                            # The knuckles' ends, in their walls over the axis, off the pin.
                            ("ends_+y", ((-0.5, 0.5), (4, 6), (2.0, 2.9))),
                            ("ends_-y", ((-0.5, 0.5), (-6, -4), (2.0, 2.9))),
                            # Each knuckle to the other leaf's plate, across X = ±3.15.
                            ("knuckle_a_+y_to_plate_b", ((2.5, 3.6), (6, 14), (-1, 1))),
                            ("knuckle_a_-y_to_plate_b", ((2.5, 3.6), (-14, -6), (-1, 1))),
                            ("knuckle_b_to_plate_a", ((-3.6, -2.5), (-4, 4), (-1, 1))),
                        )
                    ),
                    # The 3 mm pin and the 3.6 mm bore, each ±0.05, on the Y axis at ±0.1
                    # (the second review of #41: probes held them to about ±0.1).
                    cylinders=(
                        Cylinder("pin", "y", (0, 0, 0), (1.475, 1.525), kind="outer"),
                        Cylinder("bore", "y", (0, 0, 0), (1.775, 1.825)),
                        # Every knuckle's 6 mm at ±0.1: each outer face within 0.25 of r = 3
                        # is held (`checks.cylinder`), and the round probes put each there.
                        Cylinder("knuckles", "y", (0, 0, 0), (2.95, 3.05), kind="outer"),
                    ),
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
                    # Below the base circle the tooth isn't stated: ISO 53's rack, generated,
                    # is +0.9%, and the face at its stated +0.1 another 1.25% (#40 V2).
                    volume_rel=0.04,
                    inside={"tooth_+x": (16.4, 0, 4)},
                    # The bore: 6 mm ±0.05 across, its place ±0.1 (the second review of
                    # #41: one probe held both, and failed a correct bore moved 0.04).
                    cylinders=(Cylinder("bore", "z", (0, 0, 4), (2.975, 3.025), offset=0.1),),
                    outside={
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
                        # The involute near the base circle and near the tip, where straight
                        # flanks part from it, each ±0.1 mm of tooth width (the review of
                        # #41: straight 20° flanks passed the pitch and addendum rings).
                        ring(
                            "involute_base",
                            (0, 0, 4),
                            14.2,
                            n=499,
                            share=(0.569, 0.613),
                            changes=(40, 40),
                        ),
                        ring(
                            "involute_tip",
                            (0, 0, 4),
                            16.4,
                            n=499,
                            share=(0.205, 0.243),
                            changes=(40, 40),
                        ),
                        # The roots 26.25 across, r = 13.125, ±0.1 (the tips', as the text
                        # gives the roots none): solid all round at r = 13.025, and each of
                        # the 20 gaps reaching below r = 13.225 (#40 V2: held from below only,
                        # at r = 13, so a shallower root passed).
                        ring("root", (0, 0, 4), 13.025, n=181, share=(0.99, 1.0)),
                        ring("root_at_most", (0, 0, 4), 13.225, n=499, changes=(40, 40)),
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
                    # The head's 5.3 mm, ±0.1, off the plane X = 5, which cuts the head alone,
                    # past the crests (#40 V2: its top, Z = 0, had no check).
                    section_spans=(SectionSpan("head", "x", 5, "z", (5.2, 5.4)),),
                    samples=(
                        # Along the flanks: in and out at each half pitch, 12.8 pitches.
                        line(
                            "flanks",
                            (3.6, 0, 2),
                            (3.6, 0, 18),
                            n=401,
                            share=(0.3, 0.7),
                            changes=(24, 28),
                            # "the pitch exact": the mean rise to rise over 12.8 pitches, 1.25
                            # within 0.02 (a pitch of 1.15 or 1.3 passed the counts). Points
                            # 0.04 apart read it within 2 x 0.04 / 12 = 0.007.
                            period=(1.23, 1.27),
                        ),
                        # The roots at least 6.45 and at most 6.85 across, "within 0.2 mm of the
                        # profile's" 6.65 (the second review of #41: 6.40 and 6.88 passed).
                        line("roots", (0, 3.225, 2), (0, 3.225, 18), n=120, share=(0.99, 1.0)),
                        # And at most 6.85 across ("within 0.2 mm of the profile's"): gaps at
                        # r = 3.44, over whole pitches (#40 V2: roots were held from below only).
                        line(
                            "roots_at_most", (0, 3.425, 2), (0, 3.425, 17), n=120, share=(0.0, 0.95)
                        ),
                        # ISO 68-1's 60° flanks, over whole pitches so the thread's phase can't
                        # skew a share. Drawn flat, 0.63 of a line is material at r = 3.45 (a
                        # profile swept along the helix reads about 0.09 more) and
                        # 0.24 at r = 3.88, where a square thread is 0.5 at both; each window
                        # takes the profile 0.1 mm smaller or larger, as stated (#40 V2).
                        line(
                            "flanks_low", (0, -3.45, 2), (0, -3.45, 17), n=400, share=(0.52, 0.86)
                        ),
                        line("crests", (-3.88, 0, 2), (-3.88, 0, 18), n=400, share=(0.12, 0.36)),
                        # The crests "between 7.8 and 8.0 mm across": some material at r =
                        # 3.895 (the reference: 0.22), none at 4.01 (the second review of
                        # #41: 7.76 passed).
                        line(
                            "crests_at_least",
                            (0, 3.895, 2),
                            (0, 3.895, 17),
                            n=120,
                            share=(0.02, 0.5),
                        ),
                        line(
                            "past_crests", (0, -4.01, 2), (0, -4.01, 18), n=120, share=(0.0, 0.01)
                        ),
                        helix("right_hand", 3.6, 1.25, 3, 17),
                        # The head's top, Z = 0, past the crests, and the shank's end, Z = 20,
                        # each ±0.1: 24 points 0.01 apart about each, 10 of them to 0.1 (#40
                        # V2: the shank's start had no check). Few: the thread's measure is
                        # near its time.
                        line("head_top", (0, 6, -0.115), (0, 6, 0.115), n=24, share=(0.083, 0.917)),
                        line(
                            "shank_end", (0, 0, 19.885), (0, 0, 20.115), n=24, share=(0.083, 0.917)
                        ),
                    ),
                    # 60°: the share falls 2 tan 30° x 0.43 / 1.25 = 0.397 from r = 3.45 to
                    # 3.88 drawn flat; swept, the lines read about 0.018 more (the
                    # reference: 0.415). The window takes about 57° to 63° as read, so 55°
                    # (read 0.365 and 0.37) fails, as do 85° and a square thread (the second
                    # review of #41: the reference was 68°, P/8 where P/16 belongs, and 55°
                    # passed). 400 points a line, as 200 read the share only to 0.01.
                    slopes=(
                        Slope("flank_angle", "flanks_low", "crests", (0.39, 0.44)),
                        # The shank's 20 mm, ±0.1: its end's share less the head top's, 0.1
                        # 10 of 24 points.
                        Slope("shank_length", "shank_end", "head_top", (-0.417, 0.417)),
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
                    # Both cheeks' holes: each is held (`checks.cylinder`).
                    cylinders=(Cylinder("holes", "y", (0, 0, 18), (3.125, 3.175)),),
                    # The stated sizes themselves, each to ±0.1: probes on a size's two faces
                    # hold it only to ±0.2 (round 2 of #41's audit). A plane at Z = 24 cuts
                    # both cheeks, so each is clipped to its own side.
                    section_spans=(
                        SectionSpan("base_x", "z", 3, "x", (15.9, 16.1)),
                        SectionSpan("base_y", "z", 3, "y", (17.9, 18.1)),
                        SectionSpan("base_height", "y", 0, "z", (5.9, 6.1)),
                        SectionSpan("cheeks_x", "z", 24, "x", (15.9, 16.1)),
                        SectionSpan("cheek_+y", "z", 24, "y", (3.9, 4.1), clip=("y", (0, 20))),
                        SectionSpan("cheek_-y", "z", 24, "y", (3.9, 4.1), clip=("y", (-20, 0))),
                    ),
                    bbox=((-8, 8), (-9, 9), (0, 26)),
                    volume=16 * 18 * 6 + 2 * 16 * 4 * 20 - 2 * math.pi * 3.15**2 * 4,
                    volume_rel=0.04,  # every stated tolerance at its limit (#40 V2)
                    # The holes' radius 3.15 ± 0.025: in past it, out short of it.
                    inside={
                        "base": (0, 0, 3),
                        "cheek": (0, 7, 10),
                        "hole_at_most": (3.19, -7, 18),
                        # Each face of the base and the cheeks 0.1 inside it, at ±0.1 (#40
                        # round 2: the base's top, the cheeks' inner faces, ends and tops weren't
                        # probed): the base at Z = 3, the cheeks at Z = 24, over the holes.
                        "base_top": (0, 0, 5.9),
                        **mirrored({"base_end": (7.9, 0, 3)}),
                        "base_side_+y": (0, 8.9, 3),
                        "base_side_-y": (0, -8.9, 3),
                        **mirrored({"cheek_+y_end": (7.9, 7, 24), "cheek_-y_end": (7.9, -7, 24)}),
                        "cheek_+y_inner": (0, 5.1, 24),
                        "cheek_-y_inner": (0, -5.1, 24),
                        "cheek_+y_outer": (0, 8.9, 24),
                        "cheek_-y_outer": (0, -8.9, 24),
                        "cheek_+y_top": (0, 7, 25.9),
                        "cheek_-y_top": (0, -7, 25.9),
                    },
                    outside={
                        "hole": (0, -7, 18),
                        "hole_at_least": (0, 7, 21.11),
                        "between_cheeks": (0, 0, 15),
                        # And 0.1 outside it.
                        "over_base": (0, 0, 6.1),
                        **mirrored({"past_base_end": (8.1, 0, 3)}),
                        "past_base_+y": (0, 9.1, 3),
                        "past_base_-y": (0, -9.1, 3),
                        **mirrored(
                            {"past_cheek_+y_end": (8.1, 7, 24), "past_cheek_-y_end": (8.1, -7, 24)}
                        ),
                        "inside_cheek_+y": (0, 4.9, 24),
                        "inside_cheek_-y": (0, -4.9, 24),
                        "past_cheek_+y": (0, 9.1, 24),
                        "past_cheek_-y": (0, -9.1, 24),
                        "over_cheek_+y": (0, 7, 26.1),
                        "over_cheek_-y": (0, -7, 26.1),
                    },
                ),
                Member(
                    "tongue",
                    cylinders=(Cylinder("hole", "y", (0, 0, 18), (3.125, 3.175)),),
                    bbox=((-6, 6), (-4.6, 4.6), (10, 40)),
                    volume=12 * 9.2 * 30 - math.pi * 3.15**2 * 9.2,
                    volume_rel=0.03,  # every stated tolerance at its limit (#40 V2)
                    inside={"bar": (0, 0, 30), "hole_at_most": (3.19, 0, 18)},
                    outside={"hole": (0, 0, 18), "hole_at_least": (0, 0, 21.11)},
                    gaps=(Gap("clevis", distance=(0.3, 0.5)),),
                ),
                Member(
                    "pin",
                    # The head's 2 mm itself, at X = 4: off the pin, through the head.
                    section_spans=(SectionSpan("head", "x", 4, "y", (1.9, 2.1)),),
                    # ±0.05 on the pin's and the holes' diameters, each on its axis at ±0.1
                    # (the second review of #41: probes held them to ±0.06 or ±0.08).
                    cylinders=(Cylinder("pin", "y", (0, 0, 18), (2.975, 3.025), kind="outer"),),
                    bbox=((-5, 5), (-12, 10), (13, 23)),
                    volume=math.pi * 3**2 * 20 + math.pi * 5**2 * 2,
                    volume_rel=0.04,  # every stated tolerance at its limit (#40 V2)
                    # The head's inner face (Y = -10) at ±0.1, beside the shank (#40 round 2).
                    inside={
                        "pin_at_least": (2.97, 0, 18),
                        "head": (4.9, -11, 18),
                        "head_inner": (4, -10.1, 18),
                    },
                    outside={
                        "pin_at_most": (0, 0, 21.03),
                        "past_head": (0, -12.1, 18),
                        "past_head_inner": (4, -9.9, 18),
                    },
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
                    # ±0.05 on the shaft and the bores, each on the Z axis at ±0.1 (the
                    # second review of #41: probes held them to ±0.06, on one side).
                    cylinders=(Cylinder("shaft", "z", (0, 0, 20), (3.975, 4.025), kind="outer"),),
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
                    cylinders=(
                        Cylinder("bore", "z", (0, 0, 6), (4.125, 4.175)),
                        # The sleeve's 12 mm, ±0.1, on the axis (#40 V2: held to 11.8 to 16).
                        Cylinder("sleeve", "z", (0, 0, 7), (5.95, 6.05), kind="outer"),
                    ),
                    bbox=((-9, 9), (-9, 9), (0, 12)),
                    volume=math.pi * (9**2 * 2 + 6**2 * 10 - 4.15**2 * 12),
                    volume_rel=0.06,  # every stated tolerance at its limit: 5.3% (#40 V2)
                    inside={
                        "flange": (0, 8.9, 1),
                        # The flange's top, Z = 2, ±0.1, past the sleeve (#40 V2: no check).
                        "flange_top": (7.5, 0, 1.9),
                        "sleeve": (5.9, 0, 10),
                        "bore_at_most": (4.18, 0, 6),
                    },
                    outside={
                        "bore_at_least": (4.12, 0, 6),
                        "past_sleeve": (0, 8, 6),
                        "over_flange": (7.5, 0, 2.1),
                    },
                    # The flange's 2 mm, ±0.1, as a size: points 0.01 apart over 0.4 mm about
                    # its bottom and top, half in the material at 2 mm; 0.1 is 10 of 80.
                    samples=(
                        Sample(
                            "flange_thickness",
                            line("", (0, -7.5, -0.195), (0, -7.5, 0.195), n=40).points
                            + line("", (0, -7.5, 1.805), (0, -7.5, 2.195), n=40).points,
                            (0.375, 0.625),
                        ),
                    ),
                ),
                Member(
                    "collar",
                    cylinders=(
                        Cylinder("bore", "z", (0, 0, 16.3), (4.125, 4.175)),
                        # The set screw's 2.5 mm, ±0.1, along +X at Z = 16.3.
                        Cylinder("set_screw", "x", (6.5, 0, 16.3), (1.2, 1.3)),
                    ),
                    bbox=((-9, 9), (-9, 9), (12.3, 20.3)),
                    volume=math.pi * (9**2 - 4.15**2) * 8 - math.pi * 1.25**2 * (9 - 4.15),
                    volume_rel=0.035,  # every stated tolerance at its limit (#40 V2)
                    inside={
                        "ring": (0, 8.5, 16.3),
                        "bore_at_most": (0, 4.18, 16.3),
                        "set_screw_at_most": (6.5, 0, 17.65),
                    },
                    outside={
                        "set_screw": (6.5, 0, 16.3),
                        # Its 2.5 mm across, at ±0.1 (#40 V2: only its centre was held).
                        "set_screw_at_least": (6.5, 0, 17.45),
                        "bore_at_least": (0, -4.12, 16.3),
                    },
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
                    volume_rel=0.045,  # its 3 mm walls at ±0.1: about 3.5% (#40 V2)
                    inside={
                        "side": (48.5, 40, 30),
                        "back": (0, 78.5, 30),
                        "floor": (0, 40, 1.5),
                        "top": (0, 40, 58.5),
                        # The inside's faces, X = ±47, Y = 77, Z = 3 and 57, each at ±0.1:
                        # material 0.1 into the wall, none 0.1 short of it (#40 round 2).
                        "inner_+x": (47.1, 40, 30),
                        "inner_-x": (-47.1, 40, 30),
                        "inner_back": (0, 77.1, 30),
                        "inner_floor": (0, 40, 2.9),
                        "inner_top": (0, 40, 57.1),
                    },
                    outside={
                        "inside": (0, 40, 30),
                        "open_front": (0, 0.5, 30),
                        "inner_+x_out": (46.9, 40, 30),
                        "inner_-x_out": (-46.9, 40, 30),
                        "inner_back_out": (0, 76.9, 30),
                        "inner_floor_out": (0, 40, 3.1),
                        "inner_top_out": (0, 40, 56.9),
                    },
                    # Its 3 mm walls, floor, top and back, each at ±0.1: a line through each,
                    # 1.5 mm past both its faces, half of it in the material.
                    samples=tuple(
                        line(name, start, end, n=301, share=(2.9 / 6, 3.1 / 6))
                        for name, start, end in (
                            ("wall_+x", (45.5, 40, 30), (51.5, 40, 30)),
                            ("wall_-x", (-45.5, 40, 30), (-51.5, 40, 30)),
                            ("back_wall", (0, 75.5, 30), (0, 81.5, 30)),
                            ("floor_wall", (0, 40, -1.5), (0, 40, 4.5)),
                            ("top_wall", (0, 40, 55.5), (0, 40, 61.5)),
                        )
                    ),
                ),
                Member(
                    "drawer",
                    bbox=((-50, 50), (-3.5, 76.5), (0.5, 59.5)),
                    volume=93 * 77 * 46.5 - 89 * 73 * 44.5 + 100 * 3 * 59 - math.pi * 10**2 * 5,
                    volume_rel=0.05,  # every stated tolerance at its limit: 4.7% (#40 V2)
                    inside={
                        "side": (45.5, 40, 30),
                        "floor": (0, 40, 4.5),
                        "front": (0, -2, 10),
                        # The finger hole's 20 mm across, at ±0.1 (#40 V2).
                        "finger_hole_at_most": (0, -2, 48.1),
                        # The body's faces at ±0.1 (#40 round 2): its sides at X = ±46.5, its
                        # underside at Z = 3.5, its top edge at 50, and its front wall's inside
                        # 2 mm behind the plate, at Y = 1.5; and the plate's back, Y = -0.5,
                        # past the body.
                        "body_+x": (46.4, 40, 30),
                        "body_-x": (-46.4, 40, 30),
                        "underside": (0, 40, 3.6),
                        "top_edge": (45.5, 40, 49.9),
                        "front_wall": (30, 1.4, 30),
                        "plate_back_+x": (48, -0.6, 30),
                        "plate_back_-x": (-48, -0.6, 30),
                    },
                    outside={
                        "inside": (0, 40, 30),
                        "finger_hole": (0, -2, 38),
                        "finger_hole_at_least": (0, -2, 47.9),
                        "over_body": (0, 0, 52),
                        "body_+x_out": (46.6, 40, 30),
                        "body_-x_out": (-46.6, 40, 30),
                        "under_body": (0, 40, 3.4),
                        "over_top_edge": (45.5, 40, 50.1),
                        "front_wall_out": (30, 1.6, 30),
                        "behind_plate_+x": (48, -0.4, 30),
                        "behind_plate_-x": (-48, -0.4, 30),
                    },
                    # Its 2 mm walls and floor and the plate's 3 mm, each at ±0.1: a line
                    # through each, past both its faces.
                    samples=(
                        *(
                            line(name, start, end, n=201, share=(1.9 / 4, 2.1 / 4))
                            for name, start, end in (
                                ("wall_+x", (43.5, 40, 30), (47.5, 40, 30)),
                                ("wall_-x", (-43.5, 40, 30), (-47.5, 40, 30)),
                                ("back_wall", (0, 73.5, 30), (0, 77.5, 30)),
                                ("floor_wall", (0, 40, 2.5), (0, 40, 6.5)),
                            )
                        ),
                        *(
                            line(name, (x, -5, 30), (x, 1, 30), n=301, share=(2.9 / 6, 3.1 / 6))
                            for name, x in (("plate_+x", 48), ("plate_-x", -48))
                        ),
                    ),
                    # The finger hole's 20 mm at ±0.1, its axis at X = 0, Z = 38 at ±0.1.
                    cylinders=(Cylinder("finger_hole", "y", (0, -2, 38), (9.95, 10.05)),),
                    gaps=(Gap("cabinet", distance=(0.4, 0.6)),),
                    # Each gap to the cabinet, 0.4 to 0.6 "everywhere": the closest distance in
                    # a box round each face pair, clear of the corners where another pair is
                    # (round 3 of #41's audit: the Gap above holds only the closest of all).
                    region_gaps=tuple(
                        RegionGap(name, "cabinet", box, (0.4, 0.6))
                        for name, box in (
                            ("side_+x", ((45, 49), (10, 70), (10, 45))),
                            ("side_-x", ((-49, -45), (10, 70), (10, 45))),
                            ("floor", ((-40, 40), (10, 70), (1, 5))),
                            ("back", ((-40, 40), (73, 79), (10, 45))),
                            # The plate's back to the cabinet's front edge, round its opening.
                            ("plate_+x", ((47.5, 49.5), (-2, 2), (10, 45))),
                            ("plate_-x", ((-49.5, -47.5), (-2, 2), (10, 45))),
                            ("plate_top", ((-40, 40), (-2, 2), (57.5, 59))),
                            ("plate_bottom", ((-40, 40), (-2, 2), (1, 2.5))),
                        )
                    ),
                ),
            ),
        ),
        Case(
            "gear-pair",
            7,
            (
                Member(
                    "plate",
                    # The posts' 5 mm at ±0.05, each on its axis at ±0.1 (the second
                    # review of #41: probes held them to ±0.06).
                    cylinders=(
                        Cylinder("post_a", "z", (0, 0, 10), (2.475, 2.525), kind="outer"),
                        Cylinder("post_b", "z", (30.2, 0, 10), (2.475, 2.525), kind="outer"),
                    ),
                    bbox=((-12, 58), (-25, 25), (0, 14)),
                    volume=70 * 50 * 4 + 2 * math.pi * 2.5**2 * 10,
                    volume_rel=0.03,  # the 4 mm plate at ±0.1: 2.4% (#40 V2)
                    inside={
                        "post_a_at_least": (2.47, 0, 10),
                        "post_b_at_least": (30.2, 2.47, 10),
                        # The plate's top, Z = 4, and each post's own top, Z = 14, at ±0.1: the
                        # box holds only the taller post's (#40 round 2).
                        "plate_top": (50, 20, 3.9),
                        "post_a_top": (0, 0, 13.9),
                        "post_b_top": (30.2, 0, 13.9),
                    },
                    outside={
                        "post_a_at_most": (2.53, 0, 10),
                        "post_b_at_most": (30.2, -2.53, 10),
                        "over_plate": (50, 20, 4.1),
                    },
                    # The plate's 4 mm at ±0.1, clear of the posts and the gears.
                    section_spans=(SectionSpan("plate", "x", 50, "z", (3.9, 4.1)),),
                ),
                Member(
                    "gear-a",
                    bbox=((-10.5, 10.5), (-10.5, 10.5), (4.5, 10.5)),
                    volume=VOLUMES["gear-a"],
                    # Every stated tolerance at its limit, the tooth's "about 0.1 mm" and
                    # ISO 53's rack below the base circle included: about 5.9% (#40 V2).
                    volume_rel=0.06,
                    inside={"tooth_+x": (10.4, 0, 7.5)},
                    # The 5.4 mm bore at ±0.05, on the Z axis at ±0.1.
                    cylinders=(Cylinder("bore", "z", (0, 0, 7.5), (2.675, 2.725), offset=0.1),),
                    samples=(
                        # Each tooth's own width at the pitch circle, the involute's π·1.5/2 =
                        # 2.3562 mm of arc, within 0.1: 1440 points, 0.039 mm apart (round 3
                        # of #41's audit: the share holds only the teeth's mean).
                        ring(
                            "pitch",
                            (0, 0, 7.5),
                            9,
                            n=1440,
                            share=(0.48, 0.52),
                            changes=(24, 24),
                            runs=(2.2562, 2.4562),
                        ),
                        # The involute's share at r = 9.75 is 0.355 (#40 V2: only the pitch
                        # circle was held, so straight flanks passed).
                        # Its window ±0.0195 of the ring, ±0.0995 mm of the 5.105 mm pitch
                        # there (#40 round 2: ±0.02 was ±0.102 mm, over the 0.1).
                        ring(
                            "addendum",
                            (0, 0, 7.5),
                            9.75,
                            n=499,
                            share=(0.3355, 0.3745),
                            changes=(24, 24),
                        ),
                        ring(
                            "involute_base",
                            (0, 0, 7.5),
                            8.55,
                            n=499,
                            share=(0.531, 0.575),
                            changes=(24, 24),
                        ),
                        ring(
                            "involute_tip",
                            (0, 0, 7.5),
                            10.35,
                            n=499,
                            share=(0.191, 0.227),
                            changes=(24, 24),
                        ),
                        # The root's 7.125 radius at ±0.1: solid at 7.025 and gaps at 7.225
                        # (#40 round 2: at 7.0 and 7.24 it was held to -0.125/+0.115).
                        ring("root", (0, 0, 7.5), 7.025, n=181, share=(0.99, 1.0)),
                        ring("root_at_most", (0, 0, 7.5), 7.225, n=181, share=(0.0, 0.95)),
                    ),
                    gaps=(
                        Gap("gear-b", distance=(0.02, 0.3)),
                        Gap("plate", distance=(0.15, 0.25)),
                    ),
                    # 0.5 above the plate, ±0.1: under the gear's face, clear of the post
                    # (round 3 of #41's audit: the Gap above is the bore's, on the post).
                    region_gaps=(
                        RegionGap("over_plate", "plate", ((4, 7), (-2, 2), (3, 5)), (0.4, 0.6)),
                    ),
                ),
                Member(
                    "gear-b",
                    bbox=BOXES["gear-b"],
                    volume=VOLUMES["gear-b"],
                    volume_rel=0.04,  # as gear A's: +0.5% for the rack, 1.7% for the face
                    outside={"gap_-x": (30.2 - 22.4, 0, 7.5)},
                    cylinders=(Cylinder("bore", "z", (30.2, 0, 7.5), (2.675, 2.725), offset=0.1),),
                    samples=(
                        # As gear A's: 3000 points, 0.044 mm apart.
                        ring(
                            "pitch",
                            (30.2, 0, 7.5),
                            21,
                            n=3000,
                            share=(0.48, 0.52),
                            changes=(56, 56),
                            runs=(2.2562, 2.4562),
                        ),
                        ring(
                            "addendum",
                            (30.2, 0, 7.5),
                            21.75,
                            n=499,
                            share=(0.35, 0.39),
                            changes=(56, 56),
                        ),
                        ring(
                            "involute_base",
                            (30.2, 0, 7.5),
                            19.85,
                            n=499,
                            share=(0.607, 0.651),
                            changes=(56, 56),
                        ),
                        # ±0.0195 of the ring: ±0.0978 mm of the 5.015 mm pitch (#40 round 2).
                        ring(
                            "involute_tip",
                            (30.2, 0, 7.5),
                            22.35,
                            n=499,
                            share=(0.2295, 0.2685),
                            changes=(56, 56),
                        ),
                        # The root's 19.125 at ±0.1, as gear A's.
                        ring("root", (30.2, 0, 7.5), 19.025, n=181, share=(0.99, 1.0)),
                        ring("root_at_most", (30.2, 0, 7.5), 19.225, n=181, share=(0.0, 0.95)),
                    ),
                    gaps=(Gap("plate", distance=(0.15, 0.25)),),
                    region_gaps=(
                        RegionGap(
                            "over_plate", "plate", ((34.2, 44.2), (-2, 2), (3, 5)), (0.4, 0.6)
                        ),
                    ),
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
                    # The head's 5.3 mm, ±0.1, as m8-bolt's (#40 V2).
                    section_spans=(SectionSpan("head", "x", 5, "z", (5.2, 5.4)),),
                    samples=(
                        line(
                            "flanks",
                            (3.6, 0, 2),
                            (3.6, 0, 28),
                            n=301,
                            share=(0.3, 0.7),
                            changes=(39, 44),
                            period=(1.23, 1.27),
                        ),
                        line("roots", (0, 3.225, 2), (0, 3.225, 28), n=120, share=(0.99, 1.0)),
                        line(
                            "roots_at_most", (0, 3.425, 2), (0, 3.425, 27), n=120, share=(0.0, 0.95)
                        ),
                        # The 60° profile, as m8-bolt's (#40 V2).
                        line(
                            "flanks_low", (0, -3.45, 2), (0, -3.45, 27), n=300, share=(0.52, 0.86)
                        ),
                        line("crests", (-3.88, 0, 2), (-3.88, 0, 27), n=300, share=(0.12, 0.36)),
                        line(
                            "crests_at_least",
                            (0, 3.895, 2),
                            (0, 3.895, 27),
                            n=120,
                            share=(0.02, 0.5),
                        ),
                        line(
                            "past_crests", (0, -4.01, 2), (0, -4.01, 28), n=120, share=(0.0, 0.01)
                        ),
                        helix("right_hand", 3.6, 1.25, 3, 27),
                        # The head's top and the shank's end, Z = 30, each ±0.1, as m8-bolt's.
                        line("head_top", (0, 6, -0.115), (0, 6, 0.115), n=24, share=(0.083, 0.917)),
                        line(
                            "shank_end", (0, 0, 29.885), (0, 0, 30.115), n=24, share=(0.083, 0.917)
                        ),
                    ),
                    slopes=(
                        Slope("flank_angle", "flanks_low", "crests", (0.39, 0.44)),
                        # The shank's 30 mm, ±0.1, as m8-bolt's 20 (#40 V2).
                        Slope("shank_length", "shank_end", "head_top", (-0.417, 0.417)),
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
                            n=301,
                            share=(0.3, 0.7),
                            changes=(7, 11),
                            # The pitch over 4.4 pitches, read within 2 x 0.018 / 4.4 = 0.008.
                            period=(1.23, 1.27),
                        ),
                        line("bore", (0, 3.4, 10.5), (0, 3.4, 16), share=(0.0, 0.01)),
                        # The bolt's profile grown 0.15 mm, as stated: 0.32 at r = 3.55 and
                        # 0.76 at r = 4.03 drawn flat, about 0.1 less swept along the helix (the
                        # reference: 0.225, 0.74), where a square thread is 0.5 at both. Four
                        # whole pitches, so the thread's phase can't skew the share.
                        line("flanks_low", (0, -3.55, 10.5), (0, -3.55, 15.5), share=(0.12, 0.44)),
                        line("flanks_high", (-4.03, 0, 10.5), (-4.03, 0, 15.5), share=(0.56, 0.9)),
                        line("past_roots", (0, -4.25, 10.5), (0, -4.25, 16), share=(0.99, 1.0)),
                        helix("right_hand", 3.8, 1.25, 11, 15.5, n=120),
                    ),
                    # The nut's material rises 2 tan 30° x 0.48 / 1.25 = 0.443 from r = 3.55
                    # to 4.03 at 60°; the window takes about 57° to 63°.
                    slopes=(Slope("flank_angle", "flanks_high", "flanks_low", (0.415, 0.47)),),
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
                    volume_rel=0.06,  # its 2 mm walls at ±0.1: about 5.5% (#40 V2)
                    inside=SNAP_BOX_IN,
                    outside=SNAP_BOX_OUT,
                ),
                Member(
                    "lid",
                    bbox=((-31.8, 31.8), (-20, 20), (20, 32)),
                    volume=63.6 * 40 * 2 + 2 * 1.6 * 10 * 10 + 2 * 0.5 * 1 * 3 * 10,
                    volume_rel=0.055,  # its 2 mm plate at ±0.1: 4.7% (#40 V2)
                    # Each hook in its window's wall, under the window's top: it holds.
                    inside=SNAP_LID_IN,
                    outside=SNAP_LID_OUT,
                    # The plate 2 mm thick, ±0.1: its section at X = 0, clear of the arms.
                    section_spans=(SectionSpan("plate", "x", 0, "z", (1.9, 2.1)),),
                    # It rests on the rim: touching it, within the ±0.1 (#40 round 2: a lid
                    # floating over the box passed).
                    gaps=(Gap("box", distance=(0.0, 0.1)),),
                ),
            ),
        ),
        Case(
            "caster-wheel",
            7,
            (
                Member(
                    "axle",
                    # ±0.05 on the axle and the bores and holes, each on the Y axis at ±0.1
                    # (the second review of #41: probes held them to ±0.06, on one side).
                    cylinders=(Cylinder("axle", "y", (0, 0, 0), (2.475, 2.525), kind="outer"),),
                    bbox=((-2.5, 2.5), (-14, 14), (-2.5, 2.5)),
                    volume=math.pi * 2.5**2 * 28,
                    volume_rel=0.03,  # every stated tolerance at its limit (#40 V2)
                    inside={"axle_at_least": (2.47, 0, 0)},
                    outside={"axle_at_most": (0, 0, 2.53)},
                    gaps=tuple(
                        Gap(o, distance=(0.1, 0.2))
                        for o in ("wheel", "spacer-a", "spacer-b", "fork")
                    ),
                ),
                Member(
                    "wheel",
                    cylinders=(Cylinder("bore", "y", (0, 0, 0), (2.625, 2.675)),),
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
                        cylinders=(Cylinder("bore", "y", (0, 0, 0), (2.625, 2.675)),),
                        bbox=((-4.5, 4.5), (y0, y1), (-4.5, 4.5)),
                        volume=math.pi * (4.5**2 - 2.65**2) * 2.7,
                        volume_rel=0.09,  # every stated tolerance at its limit: 8.3% (#40 V2)
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
                    # Both arms' holes: each is held (`checks.cylinder`).
                    cylinders=(Cylinder("holes", "y", (0, 0, 0), (2.625, 2.675)),),
                    bbox=((-12, 12), (-13.3, 13.3), (-8, 30)),
                    volume=2 * 16 * 4 * 34 + 24 * 26.6 * 4 - 2 * math.pi * 2.65**2 * 4,
                    volume_rel=0.04,  # every stated tolerance at its limit (#40 V2)
                    inside={
                        "arm": (0, 11, 20),
                        "top": (0, 0, 28),
                        "hole_at_most": (2.68, 11.3, 0),
                        # Each arm's own faces at ±0.1, which the box, the top plate's, doesn't
                        # hold (#40 round 2): its ends at X = ±8, its faces at Y = ±9.3 and
                        # ±13.3, its foot at Z = -8; and the plate's underside, Z = 26, and its
                        # edges at Y = ±13.3 past the arms.
                        **mirrored({"arm_+y_end": (7.9, 11.3, 10), "arm_-y_end": (7.9, -11.3, 10)}),
                        "arm_+y_inner": (0, 9.4, 10),
                        "arm_-y_inner": (0, -9.4, 10),
                        "arm_+y_outer": (0, 13.2, 10),
                        "arm_-y_outer": (0, -13.2, 10),
                        "arm_+y_foot": (0, 11.3, -7.9),
                        "arm_-y_foot": (0, -11.3, -7.9),
                        "plate_underside": (0, 0, 26.1),
                        "plate_+y_edge": (10, 13.2, 28),
                        "plate_-y_edge": (10, -13.2, 28),
                    },
                    outside={
                        "hole_at_least": (0, 11.3, 2.62),
                        "between_arms": (0, 0, 10),
                        **mirrored(
                            {"past_arm_+y": (8.1, 11.3, 10), "past_arm_-y": (8.1, -11.3, 10)}
                        ),
                        "inside_arm_+y": (0, 9.2, 10),
                        "inside_arm_-y": (0, -9.2, 10),
                        "under_plate": (0, 0, 25.9),
                    },
                    # Each arm's 16 mm along X and its 4 mm along Y, at ±0.1: a line through it
                    # each way, past both its faces.
                    samples=(
                        *(
                            line(
                                f"arm_{s}_length",
                                (-9, y, 10),
                                (9, y, 10),
                                n=361,
                                share=(15.9 / 18, 16.1 / 18),
                            )
                            for s, y in (("+y", 11.3), ("-y", -11.3))
                        ),
                        *(
                            line(
                                f"arm_{s}_thickness",
                                (0, 8.3 * k, 10),
                                (0, 14.3 * k, 10),
                                n=301,
                                share=(3.9 / 6, 4.1 / 6),
                            )
                            for s, k in (("+y", 1), ("-y", -1))
                        ),
                    ),
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
                    centred=(("y", 0.0),),  # "centre it on …" (round 2 of the audit)
                    samples=(
                        # Its top carries the shelf from the wall to 100 mm out.
                        line("carries_shelf", (2, 0, -0.3), (100, 0, -0.3), share=(0.99, 1.0)),
                        # Flat on the wall: an area of its back, so its screw holes don't
                        # count against it (#40 V2: a line through two centred holes failed).
                        grid("on_the_wall", 0.3, (-5, 5), (-40, -1), share=(0.6, 1.0)),
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
                    centred=(("x", 0.0),),  # "centre it on …" (round 2 of the audit)
                    samples=(
                        # It wraps more than half the tube, so it snaps on, and leaves an
                        # opening; its bore takes the tube and grips it.
                        ring("wraps", (0, 0, -20), 10.6, axis="x", n=181, share=(0.55, 0.95)),
                        # The tube goes in: a bore of 19.5 mm or more, so it may grip the 20
                        # mm tube by up to 0.5 mm and still come out by hand (the blind
                        # oracle, #40: 19.9 refused a press grip the text allows).
                        ring("takes_tube", (0, 0, -20), 9.75, axis="x", n=181, share=(0.0, 0.01)),
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
                    # Off the panel by any gap, so it doesn't rub: 0.1 mm or more with the
                    # tolerance (the blind oracle, #40: 0.4 refused gaps the text allows).
                    within=((-25, 25), (-25, 25), (0.2, 40)),
                    spans=((20, 50), (20, 50), (10, 40)),
                    # The bore keys on the flat (X = 1.5), from Z = 4 to the shaft's tip.
                    inside={
                        "keys_flat": (1.75, 0, 8),
                        # At least 8 mm down the 12 mm shaft: to Z = 4, at ±0.1 (#40 V2).
                        "keys_flat_low": (1.75, 0, 4.1),
                        "keys_flat_high": (1.75, 0, 11.5),
                        "round_snug": (0, 3.2, 8),
                    },
                    outside={"bore": (0, 0, 8)},
                    # Snug: at most 0.15 mm off the shaft, or pressed on by up to about 0.07
                    # mm all round, 10 mm³ (#40 V2: 1 mm³ was 0.007 mm, no real press fit).
                    gaps=(Gap("shaft", interference=(0.0, 10.0), distance=(0.0, 0.15)),),
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
                    # Room for a strap "about 40 mm wide", lying along Y: what it rests on,
                    # cut 20 mm out from the wall, is 35 mm wide or more (#40 V2: the whole
                    # part's Y extent passed a wide wall plate with a narrow arm).
                    section_spans=(SectionSpan("strap_seat", "x", 20, "y", (35, 80)),),
                    holes=(Holes("screws", "x", (2.1, 2.6), 2),),
                    # 5 kg hung at the hook's far end, the worst place it could hang, on
                    # the arm 20 mm out, past any wall plate (the review of #41: at 8 mm a
                    # thick plate could take the section, and a thin arm pass).
                    load=Load("bag", "x", 20, force_n=5 * G),
                    centred=(("y", 0.0), ("z", 0.0)),  # "centre it on …" (round 2 of the audit)
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
                    centred=(("x", 0.0), ("y", 0.0)),  # "centre it on …" (round 2 of the audit)
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
                    # The spool's 65 mm width fits on it: it reaches that far from the
                    # wall, solid or hollow (the blind oracle, #40: a line through the
                    # axis, 99% solid, failed a hollow tube the text allows).
                    spans=((65, 150), None, None),
                    samples=(
                        # Clear of the 53 mm hole by 0.2 mm at least, under the spool's
                        # whole width.
                        ring("clears_hub", (40, 0, 0), 26.3, axis="x", n=181, share=(0.0, 0.01)),
                        # Its axis is the X axis, so the 53 mm hole rests on the holder
                        # near its top: material at R 24 (a spindle 48 mm across or more,
                        # loose enough to turn) along the width past any wall plate (#40
                        # V2: a thin rod on the axis would hang the spool 14 mm low).
                        line("carries_hub", (15, 0, 24), (70, 0, 24), share=(0.99, 1.0)),
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
