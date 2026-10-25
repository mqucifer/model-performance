---
name: cadquery-errors
description: CadQuery 2.8's common errors and invalid shapes, what they usually mean, and what to change
---

# Errors and what they usually mean

From CadQuery's [Class reference](https://cadquery.readthedocs.io/en/latest/classreference.html)
and [Workplane](https://cadquery.readthedocs.io/en/latest/workplane.html) pages, and
the errors 2.8.0 raises.

| Error | Usually | Change |
|---|---|---|
| `AttributeError: module 'cadquery' has no attribute ...` | a name that isn't CadQuery's | `lookup` the fragment: `makeHelix` is `cq.Wire.makeHelix` |
| `ValueError: ... must have at least one solid on the stack to union` | the other side of a `union` or `cut` holds no solid: a wire, a failed sweep, a compound of shells | check `.solids().vals()` on it; make it a solid first |
| `ValueError: No pending wires present` | an `extrude`, `revolve` or `sweep` with no 2D shape drawn since the last solid | draw the shape again on the workplane before the operation |
| `StdFail_NotDone` | OCCT couldn't do a boolean, fillet or chamfer | a fillet larger than the edge allows; faces that only touch; try a smaller radius, or overlap the solids |
| `Standard_ConstructionError`, `gp_...` | an impossible geometry: a zero length, parallel vectors, a circle of radius 0 | check the numbers that reached the call |
| a selector that picks nothing, then an `IndexError` or a `ValueError` | `faces(">Z")` on the wrong object, or a type that isn't there | print `len(wp.faces(...).vals())`; see `cadquery-selectors` |
| the part is in the wrong place | a centred `box` or `rect`, a workplane's origin, or `"XZ"`'s normal being -Y | `inspect` the STEP and compare its bounding box with the spec |

## An invalid or empty shape
- `shape.isValid()` is `False` after a boolean: often two surfaces that coincide or
  only touch. Overlap them by a little, or build the feature longer and cut it back.
- A sweep's result is a shell, not a solid: the profile wasn't closed, or it twisted.
  Close the wire, and use `isFrenet=True` along a helix (`cadquery-threads-helices`).
- `cq.exporters.export` of a hollow part writes its shell; that's fine, it's still a
  closed volume when the shell is closed.
