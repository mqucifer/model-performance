"""The case audit's checks, listed without measuring (mqucifer/model-performance#40, V2).

The audit traces every hidden check of the 21 harder cases to its spec's text, and
every value a spec states to a check (`audit.json`, held by `tests/cad_eval/test_audit.py`).
This lists each check by the name `checks.member` gives it, and what it wants, from
the case's data alone, so the audit can't fall behind a change to a case. A test in
the image holds this list to the names the real checks produce.

Each check in `audit.json` is one of:
- `stated`: the spec's text states it; `says` quotes the words.
- `derived`: it follows from what the spec states by a named standard or by arithmetic;
  `says` names the standard or the sum, and quotes what it starts from.
- `judgment`: a choice the text leaves open; `says` says why the check's window takes
  every defensible choice.
- `frame`: placement the spec gives ("So it can be checked", "Placement"); `says`
  quotes it.
"""

from __future__ import annotations

from typing import Any

from cad_eval.cases import Case

CLASSES = ("stated", "derived", "judgment", "frame")


def checks(case: Case) -> list[dict[str, Any]]:
    """Every check of `case`, as `<member>/<check>`, with what it wants."""
    found: list[dict[str, Any]] = []

    def add(member: str, name: str, wants: Any) -> None:
        found.append({"check": f"{member}/{name}", "wants": wants})

    for m in case.members:
        add(m.name, "solids", m.solids)
        if m.bbox is not None:
            for axis, want in zip("xyz", m.bbox, strict=True):
                add(m.name, f"bbox.{axis}.min", want[0])
                add(m.name, f"bbox.{axis}.max", want[1])
        if m.within is not None:
            for axis, want in zip("xyz", m.within, strict=True):
                add(m.name, f"within.{axis}", list(want))
        for axis, span in zip("xyz", m.spans or (None,) * 3, strict=True):
            if span is not None:
                add(m.name, f"span.{axis}", list(span))
        if m.volume is not None:
            add(m.name, "volume", round(m.volume, 3))
        if m.volume_range is not None:
            add(m.name, "volume", [round(v, 3) for v in m.volume_range])
        for name, point in m.inside.items():
            add(m.name, f"in.{name}", list(point))
        for name, point in m.outside.items():
            add(m.name, f"out.{name}", list(point))
        for sample in m.samples:
            if tuple(sample.share) != (0.0, 1.0):
                add(m.name, f"share.{sample.name}", list(sample.share))
            if sample.changes is not None:
                add(m.name, f"changes.{sample.name}", list(sample.changes))
            if sample.gaps is not None:
                add(m.name, f"gaps.{sample.name}", list(sample.gaps))
        for holes in m.holes:
            add(m.name, f"holes.{holes.name}", {"count": holes.count, "radius": list(holes.radius)})
        if m.load is not None:
            add(m.name, f"load.{m.load.name}", {"force_n": m.load.force_n, "arm_mm": m.load.arm_mm})
        for gap in m.gaps:
            add(m.name, f"gap.{gap.other}.interference", list(gap.interference))
            if gap.distance is not None:
                add(m.name, f"gap.{gap.other}.distance", list(gap.distance))
        if m.own_gap is not None:
            add(m.name, "own.interference", [0.0, 0.01])
            add(m.name, "own.distance", list(m.own_gap))
        for spec in m.section_spans:
            add(
                m.name,
                f"section.{spec.name}",
                {"at": f"{spec.axis}={spec.at}", "span": list(spec.span)},
            )
        if m.vents is not None:
            add(m.name, f"vents.{m.vents.name}", {"area": m.vents.area})
    return found
