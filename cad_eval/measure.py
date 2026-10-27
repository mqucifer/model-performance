"""Measure one part, inside the CAD-code evaluation's container only.

    python -I - '<request JSON>'   (this file on stdin)

It is never written into the part's directory, so a session can't change it, and
`-I` keeps a module the model wrote from shadowing an import. The request names the
file to measure (STEP or STL, relative to /work), and optionally points to probe and
a mating part's CadQuery source. The harder cases (`cad_eval/cases.py`) may also ask
for the overlap and the gap with other parts (`against`), between the shape's own
solids (`self`), its cylindrical faces (`cylinders`), a plane section's area
properties (`section`), which lines along an axis meet it (`rays`), and what it
would overhang printed as placed (`print`). It prints one line, `MARK` then JSON:
the facts, or `error`. The host compares them with the part's spec
(`cad_eval/checks.py`).

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


def gap(shape, other) -> dict:  # noqa: ANN001
    """The overlap's volume and the closest distance between two shapes: 0 where they touch."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: PLC0415

    overlap = shape.intersect(other).Volume()
    distance = BRepExtrema_DistShapeShape(shape.wrapped, other.wrapped)
    return {
        "interference": round(overlap, 4),
        "distance": round(distance.Value(), 4) if distance.IsDone() else None,
    }


def against(others: list) -> dict:
    """Each other part, from a STEP file in /work or the evaluation's own source."""
    found = {}
    for other in others:
        try:
            built = load(Path(other["path"])) if other.get("path") else mate(other["source"])
            found[other["name"]] = solids_from_shells(built)[0]
        except Exception as exc:  # noqa: BLE001
            found[other["name"]] = f"{type(exc).__name__}: {exc}"[:300]
    return found


def own(shape) -> dict:  # noqa: ANN001
    """The largest overlap and the smallest gap between a shape's own solids."""
    solids = shape.Solids()
    pairs = [gap(a, b) for i, a in enumerate(solids) for b in solids[i + 1 :]]
    if not pairs:
        return {"interference": None, "distance": None}
    distances = [p["distance"] for p in pairs if p["distance"] is not None]
    return {
        "interference": max(p["interference"] for p in pairs),
        "distance": min(distances) if distances else None,
    }


def cylinders(shape) -> list[dict]:  # noqa: ANN001
    """Each cylindrical face: its radius, axis, a point on the axis, and whether it's a hole."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface  # noqa: PLC0415
    from OCP.GeomAbs import GeomAbs_Cylinder  # noqa: PLC0415
    from OCP.TopAbs import TopAbs_REVERSED  # noqa: PLC0415

    found = []
    for face in shape.Faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        cylinder = surface.Cylinder()
        axis = cylinder.Axis()
        origin = axis.Location()
        direction = axis.Direction()
        # A cylinder's own normal points away from its axis, and a face's material is
        # behind its normal: reversed, the material is outside, so the face is a hole's.
        hole = face.wrapped.Orientation() == TopAbs_REVERSED
        found.append(
            {
                "radius": round(cylinder.Radius(), 4),
                "axis": [round(direction.X(), 4), round(direction.Y(), 4), round(direction.Z(), 4)],
                "origin": [round(origin.X(), 4), round(origin.Y(), 4), round(origin.Z(), 4)],
                "hole": hole,
            }
        )
    return found


def section(shape, request: dict) -> dict:  # noqa: ANN001
    """The material cut by the plane `axis` = `at`: area, centroid and second moments.

    The second moments are the area's, about its centroid, as a 3 by 3 matrix: for a
    plane X = at, entry [1][1] is the integral of z² over the area, the one that resists
    a load along Z.
    """
    import cadquery as cq  # noqa: PLC0415
    from OCP.BRepGProp import BRepGProp  # noqa: PLC0415
    from OCP.GProp import GProp_GProps  # noqa: PLC0415

    index = "xyz".index(request["axis"])
    normal = [0.0, 0.0, 0.0]
    normal[index] = 1.0
    origin = [0.0, 0.0, 0.0]
    origin[index] = float(request["at"])
    plane = cq.Face.makePlane(10_000, 10_000, cq.Vector(*origin), cq.Vector(*normal))
    cut = shape.intersect(plane)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(cut.wrapped, props)
    area = props.Mass()
    if area <= 0:
        return {"area": 0.0}
    centre = props.CentreOfMass()
    matrix = props.MatrixOfInertia()
    box = cut.BoundingBox()
    return {
        "area": round(area, 4),
        "centroid": [round(centre.X(), 4), round(centre.Y(), 4), round(centre.Z(), 4)],
        "moments": [[round(matrix.Value(i, j), 4) for j in (1, 2, 3)] for i in (1, 2, 3)],
        "bbox": [
            [round(box.xmin, 4), round(box.xmax, 4)],
            [round(box.ymin, 4), round(box.ymax, 4)],
            [round(box.zmin, 4), round(box.zmax, 4)],
        ],
    }


# A face overhangs when it faces down steeper than this from vertical: PrusaSlicer's
# default support threshold. A bridge is a face facing straight down, within this.
OVERHANG_DEG = 45.0
BRIDGE_DEG = 1.0
# How close to the part's lowest point a face may be and still rest on the bed, mm.
BED_TOLERANCE = 0.01


def printability(shape) -> dict:  # noqa: ANN001
    """What printing the shape as placed (+Z up, its lowest point on the bed) would hang
    over air: recorded beside the checks, never one of them.

    - `overhang_mm2`: the area of faces facing down steeper than `OVERHANG_DEG` from
      vertical, bridges included, but not those on the bed;
    - `bridges`: the regions of those facing straight down, each a connected patch;
    - `longest_bridge_mm`: the longest of their spans, each the shorter side of its
      patch's box across X and Y: the gap it crosses, if it rests on its two long sides.
    """
    import numpy as np  # noqa: PLC0415
    import trimesh  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        stl = Path(tmp) / "part.stl"
        shape.exportStl(str(stl), tolerance=MESH_TOLERANCE, angularTolerance=MESH_ANGLE)
        mesh = trimesh.load(str(stl), force="mesh")
    normals, areas = mesh.face_normals, mesh.area_faces
    lowest = mesh.bounds[0][2]
    on_bed = mesh.triangles[:, :, 2].max(axis=1) <= lowest + BED_TOLERANCE
    down = -normals[:, 2]
    over = (down > np.cos(np.radians(OVERHANG_DEG))) & ~on_bed
    flat = (down > np.cos(np.radians(BRIDGE_DEG))) & ~on_bed
    spans = []
    if flat.any():
        patches = trimesh.graph.connected_components(
            mesh.face_adjacency, nodes=np.nonzero(flat)[0], min_len=1
        )
        for patch in patches:
            points = mesh.triangles[patch].reshape(-1, 3)
            size = points.max(axis=0) - points.min(axis=0)
            spans.append(float(min(size[0], size[1])))
    return {
        "overhang_mm2": round(float(areas[over].sum()), 1),
        "bridges": len(spans),
        "longest_bridge_mm": round(max(spans), 2) if spans else 0.0,
    }


def rays(shape, request: dict) -> list[bool]:  # noqa: ANN001
    """Whether a line along `axis` through each point meets the shape: a vent is where
    one doesn't."""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter  # noqa: PLC0415
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt  # noqa: PLC0415

    index = "xyz".index(request["axis"])
    direction = [0.0, 0.0, 0.0]
    direction[index] = 1.0
    hits = []
    for across in request["points"]:
        point = list(across)
        point.insert(index, 0.0)
        found = BRepIntCurveSurface_Inter()
        found.Init(shape.wrapped, gp_Lin(gp_Pnt(*point), gp_Dir(*direction)), 1e-6)
        hits.append(bool(found.More()))
    return hits


def _point(text: str) -> tuple[float, float, float] | None:
    parts = text.split(",")
    if len(parts) != 3:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _faces(shape, name: str) -> list:  # noqa: ANN001
    """Faces named by a selector (`>Z`, `<X`, `%CYLINDER`) or the one nearest a point."""
    import cadquery as cq  # noqa: PLC0415
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: PLC0415

    point = _point(name)
    if point is None:
        return cq.Workplane().add(shape).faces(name).vals()
    vertex = cq.Vertex.makeVertex(*point)
    best, found = None, []
    for face in shape.Faces():
        d = BRepExtrema_DistShapeShape(face.wrapped, vertex.wrapped).Value()
        if best is None or d < best - 1e-9:
            best, found = d, [face]
    return found


def _none_found(what: str, shape, cylinders: list, holes: list) -> str:  # noqa: ANN001
    """Why `hole` or `diameter` found nothing, naming the faces the part does have: it
    never says there's no cylinder when there is one (#40, V5's review)."""
    from collections import Counter  # noqa: PLC0415

    kinds = Counter(f.geomType() for f in shape.Faces())
    faces = ", ".join(f"{n} {k.lower()}" for k, n in sorted(kinds.items()))
    if what == "hole" and cylinders:
        outer = sorted({_describe(f).get("diameter") for f in cylinders if f not in holes})
        sizes = ", ".join(f"Ø{d}" for d in outer)
        return (
            f"no hole (an inner cylindrical face) in the part; it has {len(cylinders)} outer "
            f"cylindrical face(s), {sizes}: `diameter x,y,z` measures one. Its faces: {faces}."
        )
    return f"no cylindrical face in the part. Its faces: {faces}."


def _describe(face) -> dict:  # noqa: ANN001
    from OCP.BRepAdaptor import BRepAdaptor_Surface  # noqa: PLC0415
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane  # noqa: PLC0415

    box = face.BoundingBox()
    out = {
        "type": face.geomType(),
        "centre": [round(v, 4) for v in face.Center().toTuple()],
        "area": round(face.Area(), 3),
        "bbox": [
            [round(box.xmin, 4), round(box.xmax, 4)],
            [round(box.ymin, 4), round(box.ymax, 4)],
            [round(box.zmin, 4), round(box.zmax, 4)],
        ],
    }
    surface = BRepAdaptor_Surface(face.wrapped)
    if surface.GetType() == GeomAbs_Plane:
        normal = face.normalAt(face.Center())
        out["normal"] = [round(v, 4) for v in normal.toTuple()]
    elif surface.GetType() == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        axis = cylinder.Axis().Direction()
        out["diameter"] = round(2 * cylinder.Radius(), 4)
        out["axis"] = [round(axis.X(), 4), round(axis.Y(), 4), round(axis.Z(), 4)]
    return out


def gauge(shape, query: str) -> dict:  # noqa: ANN001
    """The `measure` tool's answer, on the model's own part only: never the case's
    checks (mqucifer/model-performance#28).

    - `diameter x,y,z`: the cylindrical face nearest the point, a hole or an outer one (a
      pin, a shaft): its diameter, axis and which kind;
    - `hole x,y,z`: the hole (an inner cylindrical face) nearest the point;
    - `distance A B`: the closest distance between faces A and B, and for two parallel
      planes the gap along their normal;
    - `clearance FILE`: the overlap's volume and the closest distance to another of
      the model's own STEP files;
    - `position A`: where faces A are: centre, area, box, normal or diameter.

    A and B are a selector (`>Z`, `<X`, `|Z`, `%CYLINDER`, `>Z[1]`) or a point `x,y,z`
    (the face nearest it).
    """
    import cadquery as cq  # noqa: PLC0415
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: PLC0415

    words = query.split()
    if not words:
        return {"error": "query: name what to measure: hole, distance, clearance or position"}
    what, args = words[0], words[1:]
    try:
        if what in ("hole", "diameter") and len(args) == 1 and _point(args[0]):
            from OCP.TopAbs import TopAbs_REVERSED  # noqa: PLC0415

            cylinders = [f for f in shape.Faces() if f.geomType() == "CYLINDER"]
            holes = [f for f in cylinders if f.wrapped.Orientation() == TopAbs_REVERSED]
            pool = holes if what == "hole" else cylinders
            near = _faces(cq.Compound.makeCompound(pool), args[0]) if pool else []
            if not near:
                return {"error": _none_found(what, shape, cylinders, holes)}
            found = _describe(near[0])
            found["kind"] = "hole" if near[0].wrapped.Orientation() == TopAbs_REVERSED else "outer"
            return {what: found}
        if what == "distance" and len(args) == 2:
            a, b = _faces(shape, args[0]), _faces(shape, args[1])
            if not a or not b:
                return {"error": f"no faces for {args[0] if not a else args[1]}"}
            ca, cb = cq.Compound.makeCompound(a), cq.Compound.makeCompound(b)
            out: dict = {
                "distance": round(BRepExtrema_DistShapeShape(ca.wrapped, cb.wrapped).Value(), 4)
            }
            if len(a) == 1 and len(b) == 1 and a[0].geomType() == "PLANE" == b[0].geomType():
                na, nb = a[0].normalAt(a[0].Center()), b[0].normalAt(b[0].Center())
                if abs(abs(na.dot(nb)) - 1) < 1e-6:
                    out["gap_along_normal"] = round(abs((b[0].Center() - a[0].Center()).dot(na)), 4)
            return out
        if what == "clearance" and len(args) == 1:
            other = Path(args[0])
            if other.is_absolute() or ".." in other.parts or not other.is_file():
                return {"error": f"query: no file {args[0]} in the part's directory"}
            return {"clearance": gap(shape, solids_from_shells(load(other))[0])}
        if what == "position" and len(args) == 1:
            faces = _faces(shape, args[0])
            if not faces:
                return {"error": f"no faces for {args[0]}"}
            return {"faces": [_describe(f) for f in faces[:8]], "count": len(faces)}
    except Exception as exc:  # noqa: BLE001 - a bad selector is said, not raised
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
    return {
        "error": "query: one of `diameter x,y,z`, `hole x,y,z`, `distance A B`, "
        "`clearance FILE` or `position A`"
    }


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
        if request.get("against"):
            out["against"] = {
                name: gap(shape, other) if not isinstance(other, str) else {"error": other}
                for name, other in against(request["against"]).items()
            }
        if request.get("self"):
            out["self"] = own(shape)
        if request.get("cylinders"):
            out["cylinders"] = cylinders(shape)
        if request.get("section"):
            out["section"] = section(shape, request["section"])
        if request.get("sections"):
            out["sections"] = [section(shape, s) for s in request["sections"]]
        if request.get("query"):
            out = {"path": out["path"], **gauge(shape, request["query"])}
            return out
        if request.get("rays"):
            out["rays"] = rays(shape, request["rays"])
        if request.get("print"):
            out["print"] = printability(shape)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"it loads but can't be measured: {type(exc).__name__}: {exc}"[:500]
    return out


def main() -> None:
    print(MARK + json.dumps(measure(json.loads(sys.argv[1]))))


if __name__ == "__main__":
    main()
