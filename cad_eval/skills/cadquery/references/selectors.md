---
name: cadquery-selectors
description: CadQuery 2.8's string selectors for faces, edges and vertices: direction, parallel, perpendicular, type, and combining them
---

# Selectors

From CadQuery's [Selectors](https://cadquery.readthedocs.io/en/latest/selectors.html)
page, for 2.8.0. A selector filters what `.faces()`, `.edges()`, `.vertices()` or
`.solids()` pick from the objects on the stack.

| Selector | Picks | Example |
|---|---|---|
| `>Z`, `<Z` | the farthest along +Z, or along -Z | `faces(">Z")`: the top face |
| `\|Z` | parallel to Z (edges along Z, faces whose normal is across Z) | `edges("\|Z")`: the vertical edges |
| `#Z` | perpendicular to Z | `faces("#Z")`: faces whose normal is across Z |
| `+Z`, `-Z` | faces whose normal points along +Z, or -Z | `faces("-Z")` |
| `%CIRCLE`, `%LINE`, `%PLANE`, `%CYLINDER` | by geometry type | `edges("%CIRCLE")`: the round edges |
| `>Z[1]`, `<X[-2]` | the nth along a direction, from 0 | `faces(">Z[1]")`: the second from the top |

- **Combine** with `and`, `or`, `not` and brackets: `edges("|Z and >Y")`,
  `faces(">Z or <Z")`, `edges("not(<X or >X)")`.
- Any direction works: `>X`, `<Y`, or a vector, `">(1, 1, 0)"`.
- A selector that picks nothing raises later, at the operation that needs something
  selected (see `cadquery-errors`). Check with `len(wp.faces(">Z").vals())`.
- `.tag("base")` names a stage of the chain, and `.faces(">Z", tag="base")` or
  `.workplaneFromTagged("base")` goes back to it.
