---
name: cadquery-assemblies-fits
description: several parts that fit together in CadQuery 2.8: each part its own solid and file, placed as assembled, and checking the clearances between them
---

# Parts that fit together

From CadQuery's [Assemblies](https://cadquery.readthedocs.io/en/latest/assy.html) and
[Class reference](https://cadquery.readthedocs.io/en/latest/classreference.html), for
2.8.0.

## One script, one file per part
- Build each part as its own solid, already where the spec places it in the
  assembly, and export each to the file the spec names:
  `cq.exporters.export(pin, "pin.step")`.
- Derive the parts from the same numbers: a hole's diameter is the pin's plus the
  clearance, so changing one changes both.
- `cq.Assembly` holds parts and constraints for a model to view or solve; it isn't
  needed to export parts that are already placed.

## Checking a fit before `done`
- **Overlap:** `a.intersect(b)` is the shared volume; `.val().Volume()` should be 0
  for a clearance fit, and above 0 for a press fit.
- **Clearance:** the closest distance between two shapes, from OCCT:
  `from OCP.BRepExtrema import BRepExtrema_DistShapeShape` then
  `BRepExtrema_DistShapeShape(a.val().wrapped, b.val().wrapped).Value()`.
- **Where a part is:** `shape.val().BoundingBox()` gives `xmin` ... `zmax`.
- A part resting on another touches it: distance 0, overlap 0.

## Clearances, in words
A clearance is the gap on each side, so a hole is the pin's diameter plus twice the
radial clearance. A press fit is the opposite: the pin larger than the hole. The spec
gives the numbers; when it doesn't, say what you chose.
