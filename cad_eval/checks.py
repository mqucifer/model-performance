"""A part's measures against its spec: the three questions each run answers.

- `compiles`: the script the session named at `done` ran again, from a clean start, to
  exit 0, and wrote a STEP file that loads as a valid shape.
- `closed_mesh`: that shape's mesh, at the measure's tolerance, is watertight with a
  consistent winding: a volume a slicer can fill.
- `within_tolerance`: every dimension check passes, as `Part` declares them, or for
  a harder case, every check of each member, as `cad_eval/cases.py` declares them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cad_eval.cases import ALLOWED_MPA, Cylinder, Holes, Load, Member, Sample, Span
from cad_eval.parts import Part


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    expected: Any
    found: Any


def dimensions(part: Part, measured: dict[str, Any]) -> list[Check]:
    """Each dimension check on what `measure.py` found. A measure with an error fails all."""
    found: list[Check] = []
    if "error" in measured or "bbox" not in measured:
        return [Check("measured", False, "a shape", measured.get("error"))]
    found.append(
        Check("solids", measured["solids"] == part.solids, part.solids, measured["solids"])
    )
    for axis, want, got in zip("xyz", part.bbox, measured["bbox"], strict=True):
        for end, w, g in (("min", want[0], got[0]), ("max", want[1], got[1])):
            found.append(Check(f"bbox.{axis}.{end}", abs(g - w) <= part.tol, w, g))
    volume = measured["volume"]
    found.append(
        Check(
            "volume",
            abs(volume - part.volume) <= part.volume_rel * part.volume,
            round(part.volume, 3),
            volume,
        )
    )
    answers = measured.get("inside") or []
    expected = [(n, True) for n in part.inside] + [(n, False) for n in part.outside]
    for (name, want), got in zip(expected, answers, strict=False):
        found.append(Check(f"{'in' if want else 'out'}.{name}", got == want, want, got))
    if len(answers) != len(expected):
        found.append(Check("probes", False, len(expected), len(answers)))
    if part.mate is not None:
        overlap = measured.get("interference")
        ok = overlap is not None and overlap <= part.max_interference
        found.append(Check("interference", ok, f"<= {part.max_interference}", overlap))
    return found


def closed(measured: dict[str, Any]) -> bool:
    mesh = measured.get("mesh") or {}
    return bool(mesh.get("watertight") and mesh.get("winding_consistent") and mesh.get("is_volume"))


def valid(measured: dict[str, Any]) -> bool:
    return "error" not in measured and bool(measured.get("valid")) and measured.get("solids", 0) > 0


def member(m: Member, measured: dict[str, Any]) -> list[Check]:
    """A harder case's member: each of its checks that it declares, on what was measured."""
    if "error" in measured or "bbox" not in measured:
        return [Check("measured", False, "a shape", measured.get("error"))]
    found = [Check("solids", measured["solids"] == m.solids, m.solids, measured["solids"])]
    box = measured["bbox"]
    if m.bbox is not None:
        for axis, want, got in zip("xyz", m.bbox, box, strict=True):
            for end, w, g in (("min", want[0], got[0]), ("max", want[1], got[1])):
                found.append(Check(f"bbox.{axis}.{end}", abs(g - w) <= m.tol, w, g))
            # The size itself to its tolerance: each end alone holds it to twice that
            # (the second review of #41).
            size, wanted = round(got[1] - got[0], 4), round(want[1] - want[0], 4)
            found.append(Check(f"size.{axis}", abs(size - wanted) <= m.tol, wanted, size))
    if m.within is not None:
        for axis, (low, high), (got_low, got_high) in zip("xyz", m.within, box, strict=True):
            ok = got_low >= low - m.tol and got_high <= high + m.tol
            found.append(Check(f"within.{axis}", ok, [low, high], [got_low, got_high]))
    for axis, span, (got_low, got_high) in zip("xyz", m.spans or (None,) * 3, box, strict=True):
        if span is not None:
            size = round(got_high - got_low, 4)
            found.append(Check(f"span.{axis}", span[0] <= size <= span[1], list(span), size))
    volume = measured["volume"]
    if m.volume is not None:
        ok = abs(volume - m.volume) <= m.volume_rel * m.volume
        found.append(Check("volume", ok, round(m.volume, 3), volume))
    if m.volume_range is not None:
        low, high = m.volume_range
        found.append(Check("volume", low <= volume <= high, [low, high], volume))
    answers = measured.get("inside") or []
    expected = [(n, True) for n in m.inside] + [(n, False) for n in m.outside]
    if len(answers) != len(m.probes()):
        return [*found, Check("probes", False, len(m.probes()), len(answers))]
    for (name, want), got in zip(expected, answers, strict=False):
        found.append(Check(f"{'in' if want else 'out'}.{name}", got == want, want, got))
    at = len(expected)
    shares: dict[str, float] = {}
    for sample in m.samples:
        got = answers[at : at + len(sample.points)]
        at += len(sample.points)
        shares[sample.name] = sum(got) / len(got) if got else 0.0
        found.extend(sampled(sample, got))
    for slope in m.slopes:
        value = round(shares.get(slope.high, 0.0) - shares.get(slope.low, 0.0), 4)
        ok = slope.span[0] <= value <= slope.span[1]
        found.append(Check(f"slope.{slope.name}", ok, list(slope.span), value))
    for spec in m.cylinders:
        found.extend(cylinder(spec, measured.get("cylinders") or []))
    for holes in m.holes:
        count = holes_found(holes, measured.get("cylinders") or [])
        found.append(Check(f"holes.{holes.name}", count >= holes.count, holes.count, count))
    if m.load is not None:
        found.append(load(m.load, measured.get("section") or {}, box))
    for gap in m.gaps:
        found.extend(
            gapped(
                f"gap.{gap.other}",
                gap.interference,
                gap.distance,
                (measured.get("against") or {}).get(gap.other),
            )
        )
    if m.own_gap is not None:
        found.extend(gapped("own", (0.0, 0.01), m.own_gap, measured.get("self")))
    for k, spec in enumerate(m.section_spans):
        cut = (measured.get("sections") or [{}] * len(m.section_spans))[k] or {}
        extent = 0.0
        if cut.get("area"):
            low, high = cut["bbox"]["xyz".index(spec.across)]
            extent = round(high - low, 4)
        ok = spec.span[0] <= extent <= spec.span[1]
        found.append(Check(f"section.{spec.name}", ok, list(spec.span), extent))
    if m.vents is not None:
        hits = measured.get("rays") or []
        area = round((len(hits) - sum(hits)) * m.vents.step**2, 1) if hits else None
        ok = area is not None and len(hits) == len(m.vents.points()) and area >= m.vents.area
        found.append(Check(f"vents.{m.vents.name}", ok, f">= {m.vents.area} mm²", area))
    return found


def sampled(sample: Sample, inside: list[bool]) -> list[Check]:
    share = round(sum(inside) / len(inside), 4) if inside else 0.0
    low, high = sample.share
    # A share whose window is 0 to 1 can't fail: no check (#40 V2), only its changes'.
    found = []
    if (low, high) != (0.0, 1.0):
        found.append(Check(f"share.{sample.name}", low <= share <= high, list(sample.share), share))
    if sample.changes is not None:
        pairs = zip(inside, inside[1:] + inside[:1] if sample.closed else inside[1:], strict=False)
        changes = sum(a != b for a, b in pairs)
        low_c, high_c = sample.changes
        ok = low_c <= changes <= high_c
        found.append(Check(f"changes.{sample.name}", ok, list(sample.changes), changes))
    if sample.period is not None:
        rises = [k for k in range(1, len(inside)) if inside[k] and not inside[k - 1]]
        found_period = None
        if len(rises) >= 2:
            found_period = round((rises[-1] - rises[0]) / (len(rises) - 1) * sample.spacing, 4)
        ok = found_period is not None and sample.period[0] <= found_period <= sample.period[1]
        found.append(Check(f"period.{sample.name}", ok, list(sample.period), found_period))
    if sample.gaps is not None:
        widths = gap_widths(inside, sample.spacing)
        low_g, high_g = sample.gaps
        ok = bool(widths) and all(low_g <= w <= high_g for w in widths)
        found.append(Check(f"gaps.{sample.name}", ok, list(sample.gaps), widths))
    return found


def gap_widths(inside: list[bool], spacing: float) -> list[float]:
    """Each run of points outside between two inside, as a width in mm: the run's
    points and one spacing more, the distance between the material on either side."""
    widths, run, started = [], 0, False
    for point in inside:
        if point:
            if started and run:
                widths.append(round((run + 1) * spacing, 3))
            started, run = True, 0
        elif started:
            run += 1
    return widths


def cylinder(spec: Cylinder, faces: list[dict[str, Any]]) -> list[Check]:
    """A stated cylinder's radius and place, off the cylindrical faces of its kind along
    its axis within a millimetre of where it should be. Every one within 0.25 mm of the
    stated radius is held, so two coaxial holes (a fork's) and a face OCCT cut in halves
    are each held; the worst is reported. With none that close, the nearest, to fail."""
    index = "xyz".index(spec.axis)
    want = (spec.radius[0] + spec.radius[1]) / 2
    near = []
    for face in faces:
        if bool(face.get("hole")) != (spec.kind == "hole"):
            continue
        if abs(abs(face["axis"][index]) - 1) > 1e-3:
            continue
        across = [v for k, v in enumerate(face["origin"]) if k != index]
        should = [v for k, v in enumerate(spec.through) if k != index]
        offset = math.dist(across, should)
        if offset <= spec.offset + 1.0:
            near.append((abs(face["radius"] - want), face["radius"], round(offset, 4)))
    if not near:
        return [Check(f"cylinder.{spec.name}", False, f"a {spec.kind} along {spec.axis}", None)]
    held = [f for f in near if f[0] <= 0.25] or [min(near)]
    radius = max(held)[1]
    offset = max(f[2] for f in held)
    return [
        Check(
            f"cylinder.{spec.name}.radius",
            spec.radius[0] <= radius <= spec.radius[1],
            list(spec.radius),
            radius,
        ),
        Check(f"cylinder.{spec.name}.position", offset <= spec.offset, f"<= {spec.offset}", offset),
    ]


def holes_found(holes: Holes, cylinders: list[dict[str, Any]]) -> int:
    """The distinct hole axes along `holes.axis` of a radius in range: a hole cut in
    halves, as OCCT often makes one, counts once."""
    index = "xyz".index(holes.axis)
    axes: list[tuple[float, float]] = []
    for c in cylinders:
        if not c.get("hole") or abs(abs(c["axis"][index]) - 1) > 1e-3:
            continue
        if not holes.radius[0] <= c["radius"] <= holes.radius[1]:
            continue
        across = tuple(round(v, 2) for k, v in enumerate(c["origin"]) if k != index)
        if all(math.dist(across, a) > 0.05 for a in axes):
            axes.append(across)  # type: ignore[arg-type]
    return len(axes)


def stress(spec: Load, section: dict[str, Any], box: Any = None) -> float | None:
    """The bending stress at the section, MPa, by `Load`'s simplification; None with no
    material there. `box` is the part's bounding box, for a load at its far end."""
    if not section.get("area"):
        return None
    arm = spec.arm_mm
    if arm is None:
        arm = box["xyz".index(spec.axis)][1] - spec.at
    normal, along = "xyz".index(spec.axis), "xyz".index(spec.along)
    (across,) = {0, 1, 2} - {normal, along}
    second = section["moments"][across][across]
    low, high = section["bbox"][along]
    centre = section["centroid"][along]
    far = max(abs(high - centre), abs(centre - low))
    if second <= 0:
        return None
    return round(spec.force_n * arm * far / second, 3)


def load(spec: Load, section: dict[str, Any], box: Any = None) -> Check:
    found = stress(spec, section, box)
    ok = found is not None and found <= ALLOWED_MPA
    return Check(f"load.{spec.name}", ok, f"<= {round(ALLOWED_MPA, 2)} MPa (simplified)", found)


def gapped(
    name: str, interference: Span, distance: Span | None, found: dict[str, Any] | None
) -> list[Check]:
    if not found or "error" in found:
        return [Check(name, False, "measured", (found or {}).get("error"))]
    overlap = found.get("interference")
    ok = overlap is not None and interference[0] <= overlap <= interference[1]
    checks = [Check(f"{name}.interference", ok, list(interference), overlap)]
    if distance is not None:
        gap = found.get("distance")
        ok = gap is not None and distance[0] <= gap <= distance[1]
        checks.append(Check(f"{name}.distance", ok, list(distance), gap))
    return checks
