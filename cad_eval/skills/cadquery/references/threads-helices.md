---
name: cadquery-threads-helices
description: helices, threads and springs in CadQuery 2.8: cq.Wire.makeHelix, sweeping a profile along it, and fusing a thread onto a core so the result is valid
---

# Helices, threads and sweeps

From CadQuery's [Class reference](https://cadquery.readthedocs.io/en/latest/classreference.html)
(`Wire.makeHelix`, `Solid.sweep`, `Workplane.sweep`), for 2.8.0. CadQuery has no thread
function of its own: a thread is a profile swept along a helix.

## The helix
- `cq.Wire.makeHelix(pitch, height, radius, center=Vector(0, 0, 0), dir=Vector(0, 0, 1),
  angle=360.0, lefthand=False)`: a right-hand helix by default, rising `pitch` per
  turn, `height` tall, starting at `center + (radius, 0, 0)`. It's a class method of
  `cq.Wire`: there's no `cq.makeHelix` or `Workplane.makeHelix`.
- `lefthand=True` turns it the other way.

## Sweeping a profile along it
- Draw the profile as a closed wire in a plane that holds the helix's start point,
  e.g. on `cq.Workplane("XZ")` at `x = radius`: on `"XZ"`, a point `(x, y)` is at
  X = x, Z = y.
- `cq.Solid.sweep(outerWire, innerWires, path, makeSolid=True, isFrenet=False, ...)`:
  for a helix, pass **`isFrenet=True`**, so the profile turns with the helix and
  doesn't twist away from the axis.
- From a workplane: `cq.Workplane("XZ").polyline(points).close().sweep(cq.Workplane().add(helix), isFrenet=True)`.

## A thread that stays valid
A swept thread unioned straight onto a cylinder of the same length often gives an
invalid shape or a compound with no solid. What works:
1. Make the profile reach a little into the core (0.1 mm below the root), so the two
   overlap rather than touch.
2. Sweep along a helix longer than the thread, starting a pitch below it and ending a
   pitch above, and make the core cylinder just as long.
3. `core.fuse(thread)`, then `.intersect()` it with a cylinder of the thread's real
   length, which cuts both ends square.
4. Union the head or anything else onto that, and check `isValid()`.

## An ISO metric thread's numbers
For a pitch P, ISO 68-1's basic profile has 60° flanks, a height H = 0.866 P, a flat
of P/8 at the crest and P/4 at the root, and a minor diameter of d - 1.0825 P.
M8 × 1.25: crests 8 mm across, roots 6.647 mm. A nut's thread is the same profile
grown by the clearance it needs.

## Springs and coils
The same sweep with a circle for the profile: a circle on a plane square to the
helix at its start, swept with `isFrenet=True`.
