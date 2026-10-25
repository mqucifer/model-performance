"""Measure one part, inside the CAD-code evaluation's container only.

    python -I - '<request JSON>'   (this file on stdin)

It is never written into the part's directory, so a session can't change it, and
`-I` keeps a module the model wrote from shadowing an import. The request names the
file to measure (STEP or STL, relative to /work), and optionally points to probe and
a mating part's CadQuery source. It prints one line, `MARK` then JSON: the facts, or
`error`. The host compares them with the part's spec (`cad_eval/checks.py`).

Standard library, CadQuery and trimesh: what the image holds.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

MARK = "CAD_EVAL_MEASURE "
# How fine the mesh is that `closed` is judged on, in mm and radians.
MESH_TOLERANCE = 0.01
MESH_ANGLE = 0.1
# How close to a face a probe may be and still count as inside.
PROBE_TOLERANCE = 1e-3


def load(path: Path):  # noqa: ANN201 - cadquery is the container's
    import cadquery as cq  # noqa: PLC0415

    if path.suffix.lower() not in (".step", ".stp"):
        raise ValueError(f"measures a STEP file (.step or .stp), not {path.suffix or 'no suffix'}")
    return cq.importers.importStep(str(path)).val()


def solids_from_shells(shape):  # noqa: ANN001, ANN201
    """A solid from each closed shell, for a STEP that holds no solid: and how many.

    CadQuery 2.8's `cq.exporters.export` of a Workplane writes a shelled solid (an open
    box, a cup) as its bare closed shell, which a slicer fills as it would the solid.
    An open shell stays as it is, and fails as no solid.
    """
    import cadquery as cq  # noqa: PLC0415
    from OCP.BRep import BRep_Tool  # noqa: PLC0415
    from OCP.ShapeFix import ShapeFix_Solid  # noqa: PLC0415
    from OCP.TopoDS import TopoDS  # noqa: PLC0415

    if shape.Solids():
        return shape, 0
    closed = [s for s in shape.Shells() if BRep_Tool.IsClosed_s(s.wrapped)]
    if not closed:
        return shape, 0
    made = [
        cq.Shape.cast(ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(s.wrapped))) for s in closed
    ]
    return (made[0] if len(made) == 1 else cq.Compound.makeCompound(made)), len(made)


def facts(shape) -> dict:  # noqa: ANN001
    import trimesh  # noqa: PLC0415

    box = shape.BoundingBox()
    found = {
        "valid": bool(shape.isValid()),
        "solids": len(shape.Solids()),
        "faces": len(shape.Faces()),
        "bbox": [
            [round(box.xmin, 4), round(box.xmax, 4)],
            [round(box.ymin, 4), round(box.ymax, 4)],
            [round(box.zmin, 4), round(box.zmax, 4)],
        ],
        "volume": round(shape.Volume(), 3),
        "area": round(shape.Area(), 3),
    }
    with tempfile.TemporaryDirectory() as tmp:
        stl = Path(tmp) / "part.stl"
        shape.exportStl(str(stl), tolerance=MESH_TOLERANCE, angularTolerance=MESH_ANGLE)
        mesh = trimesh.load(str(stl), force="mesh")
    found["mesh"] = {
        "triangles": len(mesh.faces),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "is_volume": bool(mesh.is_volume),
    }
    return found


def inside(shape, points: list) -> list[bool]:  # noqa: ANN001
    import cadquery as cq  # noqa: PLC0415

    return [bool(shape.isInside(cq.Vector(*p), PROBE_TOLERANCE)) for p in points]


def mate(source: str):  # noqa: ANN201
    """The mating part, built from the evaluation's own source, which names it `mate`."""
    import cadquery as cq  # noqa: PLC0415

    space: dict = {"cq": cq}
    exec(source, space)  # noqa: S102 - the evaluation's own code, in the container
    built = space["mate"]
    return built.val() if hasattr(built, "val") else built


def measure(request: dict) -> dict:
    out: dict = {"path": request["path"]}
    path = Path(request["path"])
    if path.is_absolute() or ".." in path.parts:
        return {**out, "error": "the path is relative to the part's directory, inside it"}
    if not path.is_file():
        return {**out, "error": f"no such file: {path}"}
    try:
        shape = load(path)
    except Exception as exc:  # noqa: BLE001 - whatever fails to load is said, not raised
        return {**out, "error": f"it doesn't load: {type(exc).__name__}: {exc}"[:500]}
    try:
        shape, out["solids_from_shells"] = solids_from_shells(shape)
        out.update(facts(shape))
        if request.get("probes"):
            out["inside"] = inside(shape, request["probes"])
        if request.get("mate"):
            other = mate(request["mate"])
            out["interference"] = round(shape.intersect(other).Volume(), 4)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"it loads but can't be measured: {type(exc).__name__}: {exc}"[:500]
    return out


def main() -> None:
    print(MARK + json.dumps(measure(json.loads(sys.argv[1]))))


if __name__ == "__main__":
    main()
