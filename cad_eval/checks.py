"""A part's measures against its spec: the three questions each run answers.

- `compiles`: the script the session named at `done` ran again, from a clean start, to
  exit 0, and wrote a STEP file that loads as a valid shape.
- `closed_mesh`: that shape's mesh, at the measure's tolerance, is watertight with a
  consistent winding: a volume a slicer can fill.
- `within_tolerance`: every dimension check passes, as `Part` declares them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
