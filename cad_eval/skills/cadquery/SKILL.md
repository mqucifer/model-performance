---
name: cadquery
description: how to build a part in CadQuery 2.8 from a spec: sketch, then features, then checks, and which reference to read for what
---

# Building a part in CadQuery 2.8

Distilled from CadQuery's documentation for the version this container runs, 2.8.0
([Quickstart](https://cadquery.readthedocs.io/en/latest/quickstart.html),
[Primer](https://cadquery.readthedocs.io/en/latest/primer.html)). When a name here
isn't enough, the `lookup` tool gives the installed library's own signature and
docstring: use it before guessing a name.

## The approach

1. **Read the spec for its frame.** Where is the origin, which way is up, which face
   sits where? Write those numbers down as constants at the top of the script, and
   build every feature from them.
2. **Sketch, then extrude, revolve, loft or sweep** the base solid. Most parts are a
   `cq.Workplane` chain: a 2D sketch on a plane, then one operation that makes a
   solid (`extrude`, `revolve`, `loft`, `sweep`).
3. **Add features on selected faces:** holes, pockets, bosses, fillets and chamfers,
   each on a face or edge picked with a selector.
4. **Combine solids** with `union`, `cut` and `intersect` when a feature is easier to
   make as its own solid.
5. **Export** with `cq.exporters.export(part, "part.step")`, one file per part.
6. **Check what you made:** `inspect` the STEP file. Its bounding box tells you where
   the part is; compare it with the spec's placement before anything else.

## Which reference to read

| Read | When |
|---|---|
| `cadquery-sketch-extrude` | making the base solid: workplanes, 2D shapes, extrude, revolve, loft, holes, arrays |
| `cadquery-selectors` | picking a face or an edge to work on: `faces(">Z")`, `edges("\|Z")` and the rest |
| `cadquery-threads-helices` | a thread, a spring, a helix, or any profile swept along a path |
| `cadquery-assemblies-fits` | several parts that fit together, each in its own file, placed as assembled |
| `cadquery-errors` | an exception or an invalid shape: what it usually means and what to change |

## Habits that save turns

- **Name things with the API as it is.** `cq.Wire.makeHelix`, not `cq.makeHelix`;
  `cq.Solid.makeCylinder`, `cq.Workplane.box`. If you're unsure, `lookup` it.
- **One script, run often.** Write the whole part, run it, read the error, change
  one thing.
- **Keep a shape valid.** After a boolean, `shape.isValid()` should be `True`; a part
  that isn't valid won't be measured.
- **Units are millimetres**, angles in degrees unless an argument says radians.
