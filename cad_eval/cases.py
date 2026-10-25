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
    first): a gear's teeth or a thread's turns, counted.
    """

    name: str
    points: tuple[Point, ...]
    share: Span = (0.0, 1.0)
    changes: tuple[int, int] | None = None
    closed: bool = False


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
) -> Sample:
    """`n` points from `start` to `end`, both included."""
    points = tuple(
        tuple(round(a + (b - a) * k / (n - 1), 3) for a, b in zip(start, end, strict=True))
        for k in range(n)
    )
    return Sample(name, points, share, changes)  # type: ignore[arg-type]


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
    the section, so the moment is their product. The stress is M·c/I, with I the
    section's second moment about its centroid across the load, and c the farthest
    material from that centroid along the load. It passes at no more than
    `ALLOWED_MPA`. It ignores the screws, shear, the stress raised at corners, and
    the layers' direction: a check that a section isn't far too thin, no more.
    """

    name: str
    axis: str
    at: float
    force_n: float
    arm_mm: float
    along: str = "z"


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


CASES: dict[str, Case] = {}
# The first run's cases: two of each kind's, and one more of the hardest.
FIRST: tuple[str, ...] = ()
