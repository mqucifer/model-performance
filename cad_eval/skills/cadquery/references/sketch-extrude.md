---
name: cadquery-sketch-extrude
description: CadQuery 2.8's workplanes, 2D shapes and the operations that make a solid: extrude, revolve, loft, holes and arrays
---

# Workplanes, sketches and solids

From CadQuery's [Workplane](https://cadquery.readthedocs.io/en/latest/workplane.html),
[API reference](https://cadquery.readthedocs.io/en/latest/apireference.html) and
[Examples](https://cadquery.readthedocs.io/en/latest/examples.html), for 2.8.0.

## Workplanes
- `cq.Workplane("XY")` starts on the XY plane at the origin, its normal +Z. The named
  planes include `"XY"`, `"YZ"`, `"XZ"`, `"front"`, `"top"` and `"right"`. On `"XZ"`
  the normal is -Y, so `extrude(d)` goes towards -Y.
- `.workplane(offset=d)` moves the plane along its normal; `.center(x, y)` moves its
  origin within it; `cq.Workplane("XY", origin=(x, y, z))` starts it anywhere.
- `.transformed(offset=(x, y, z), rotate=(rx, ry, rz))` moves and turns it.
- `.faces(">Z").workplane()` puts a new plane on the selected face, its origin at the
  face's centre (see `cadquery-selectors`).

## 2D shapes
- `.rect(w, h)`, `.circle(r)`, `.ellipse(a, b)`, `.polygon(n, d)` (d is the diameter
  of the circle through its corners), `.slot2D(length, width)`.
- `.polyline(points).close()` for any outline; `.lineTo`, `.hLine`, `.vLine`,
  `.threePointArc`, `.spline` to draw one segment at a time.
- Shapes are centred by default; `.rect(w, h, centered=False)` puts the corner at the
  origin.
- A second shape inside the first makes a hole when extruded:
  `.circle(10).circle(4).extrude(5)` is a tube.

## Making a solid
- `.extrude(d)`: along the plane's normal. `extrude(d, both=True)` goes both ways,
  `d` each side. A negative `d` goes the other way.
- `.revolve(angleDegrees, axisStart, axisEnd)`: round an axis in the plane's own
  coordinates.
- `.loft()`: through several wires on offset workplanes, e.g. a circle, then
  `.workplane(offset=10).rect(...)`.
- `.box(x, y, z)` and `.cylinder(height, radius)` are centred on the plane's origin;
  `centered=(True, True, False)` sits the box on the plane.
- `cq.Solid.makeBox`, `cq.Solid.makeCylinder(radius, height, pnt, dir)`,
  `cq.Solid.makeCone` make solids directly, without a workplane.

## Features
- `.hole(diameter, depth=None)` through the solid from the selected face's plane;
  `.cboreHole(d, cboreDiameter, cboreDepth)` and `.cskHole(d, cskDiameter, cskAngle)`.
- `.pushPoints([(x, y), ...])`, `.rarray(xSpacing, ySpacing, xCount, yCount)` and
  `.polarArray(radius, startAngle, angle, count)` place the next shape or hole at
  each point.
- `.shell(thickness)` hollows the solid, opening the faces selected before it:
  `.faces(">Z").shell(-2)` is an open box with 2 mm walls inward.
- `.fillet(r)` and `.chamfer(d)` on selected edges: `.edges("|Z").fillet(2)`.
- `.union(other)`, `.cut(other)`, `.intersect(other)` combine solids;
  `.translate((x, y, z))`, `.rotate(axisStart, axisEnd, degrees)` and
  `.mirror("YZ")` move them.

## Exporting
- `cq.exporters.export(workplane_or_shape, "part.step")`: the file type follows the
  name. ([Import and export](https://cadquery.readthedocs.io/en/latest/importexport.html))
