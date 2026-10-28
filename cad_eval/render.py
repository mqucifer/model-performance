"""Render STEP parts to a PNG with VTK, inside the CAD-code evaluation's v2 image only.

    python -I - '<request JSON>'   (this file on stdin)

The `view` tool's picture (mqucifer/model-performance#29, #40). VTK renders offscreen
with OSMesa, in the v2 image (the CadQuery image plus `libosmesa6`, and indexes). Parts
are drawn flat-shaded, each in its own colour, with their feature edges in black (sharp
edges, boundaries and silhouettes): a gear's teeth and a hole read by their edges. It
prints one line, `MARK` then JSON with the PNG as base64, or `error`.

The request: `files`, each part's STEP path (relative to /work); `view`, one of `top`,
`front`, `side`, `iso`, `section`, `exploded`; for a section, `plane`
({"axis": "x", "at": 12.5}), drawn looking at the cut, with the cut face in dark grey;
`keepouts`, more of the model's own STEP files (a board or a mating part it modelled
from the spec), drawn translucent red; and `size` in pixels. Only the model's files are
drawn: nothing of the case's, which an unseen part wouldn't have (#40, A1).
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

MARK = "CAD_EVAL_VIEW "
PALETTE = [
    (0.55, 0.65, 0.80),
    (0.90, 0.65, 0.40),
    (0.55, 0.78, 0.55),
    (0.75, 0.60, 0.82),
    (0.85, 0.80, 0.45),
]
COLOURS = ["blue", "orange", "green", "purple", "yellow"]
KEEP_OUT = (0.90, 0.15, 0.15)
CUT = (0.30, 0.30, 0.30)
# Each view: where the camera sits, from the parts' centre, and the screen's up.
VIEWS = {
    "top": ((0, 0, 1), (0, 1, 0)),
    "front": ((0, -1, 0), (0, 0, 1)),
    "side": ((1, 0, 0), (0, 0, 1)),
    "iso": ((1, -1, 1), (0, 0, 1)),
    "exploded": ((1, -1, 1), (0, 0, 1)),
}
FEATURE_ANGLE = 30.0  # degrees between faces that makes an edge a feature


def polydata(shape, work: Path, name: str):  # noqa: ANN001, ANN201
    """The shape's mesh as VTK polydata, through an STL in a scratch directory."""
    import vtk  # noqa: PLC0415

    stl = work / f"{name}.stl"
    shape.exportStl(str(stl), tolerance=0.02, angularTolerance=0.1)
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(stl))
    reader.Update()
    return reader.GetOutput()


def actors(data, colour, renderer, opacity: float = 1.0) -> None:  # noqa: ANN001
    """The surface, flat-shaded, and its feature edges in black."""
    import vtk  # noqa: PLC0415

    surface = vtk.vtkPolyDataMapper()
    surface.SetInputData(data)
    body = vtk.vtkActor()
    body.SetMapper(surface)
    body.GetProperty().SetColor(*colour)
    body.GetProperty().SetOpacity(opacity)
    body.GetProperty().SetInterpolationToFlat()
    surface.SetResolveCoincidentTopologyToPolygonOffset()
    renderer.AddActor(body)
    if opacity < 1.0:
        return
    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(data)
    edges.SetFeatureAngle(FEATURE_ANGLE)
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOn()
    edges.ManifoldEdgesOff()
    edges.NonManifoldEdgesOn()
    edges.ColoringOff()
    lines = vtk.vtkPolyDataMapper()
    lines.SetInputConnection(edges.GetOutputPort())
    outline = vtk.vtkActor()
    outline.SetMapper(lines)
    outline.GetProperty().SetColor(0, 0, 0)
    outline.GetProperty().SetLineWidth(1.5)
    renderer.AddActor(outline)
    silhouette = vtk.vtkPolyDataSilhouette()
    silhouette.SetInputData(data)
    silhouette.SetCamera(renderer.GetActiveCamera())
    silhouette_map = vtk.vtkPolyDataMapper()
    silhouette_map.SetInputConnection(silhouette.GetOutputPort())
    silhouette_actor = vtk.vtkActor()
    silhouette_actor.SetMapper(silhouette_map)
    silhouette_actor.GetProperty().SetColor(0, 0, 0)
    silhouette_actor.GetProperty().SetLineWidth(1.5)
    renderer.AddActor(silhouette_actor)


def render(request: dict) -> dict:  # noqa: C901, PLR0912, PLR0915
    import cadquery as cq  # noqa: PLC0415
    import vtk  # noqa: PLC0415

    view = request.get("view", "iso")
    size = int(request.get("size", 768))
    files = request.get("files") or []
    shapes = []
    for path in files:
        p = Path(path)
        if p.is_absolute() or ".." in p.parts or not p.is_file():
            return {"error": f"query: no file {path} in the part's directory"}
        shapes.append(cq.importers.importStep(str(p)).val())
    if not shapes:
        return {"error": "query: name at least one STEP file"}
    plane = request.get("plane") or {}
    axis = None
    if view == "section":
        if plane.get("axis") not in ("x", "y", "z") or not isinstance(plane.get("at"), int | float):
            return {"error": "query: a section needs `axis` x, y or z, and `at`, a number"}
        axis = "xyz".index(plane["axis"])
        position = [0, 0, 0]
        position[axis] = -1  # looking from the side of the cut that's taken away
        camera = (tuple(position), (0, 0, 1) if axis != 2 else (0, 1, 0))
    elif view in VIEWS:
        camera = VIEWS[view]
    else:
        return {"error": f"query: view is one of {', '.join([*VIEWS, 'section'])}"}
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(1, 1, 1)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(size, size)
    window.AddRenderer(renderer)
    centre = [sum(s.Center().toTuple()[i] for s in shapes) / len(shapes) for i in range(3)]
    caption = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for k, shape in enumerate(shapes):
            colour = PALETTE[k % len(PALETTE)]
            if view == "exploded" and len(shapes) > 1:
                offset = [a - b for a, b in zip(shape.Center().toTuple(), centre, strict=True)]
                norm = sum(o * o for o in offset) ** 0.5
                if norm > 1e-9:
                    spread = 0.6 * max(norm, 10.0) / norm
                    shape = shape.translate(cq.Vector(*[o * spread for o in offset]))
            data = polydata(shape, work, f"part{k}")
            if view == "section":
                origin = [0.0, 0.0, 0.0]
                origin[axis] = float(plane["at"])
                normal = [0.0, 0.0, 0.0]
                normal[axis] = 1.0
                cutter = vtk.vtkPlane()
                cutter.SetOrigin(*origin)
                cutter.SetNormal(*normal)
                clip = vtk.vtkClipPolyData()
                clip.SetInputData(data)
                clip.SetClipFunction(cutter)
                clip.Update()
                data = clip.GetOutput()
                face = cq.Face.makePlane(10_000, 10_000, cq.Vector(*origin), cq.Vector(*normal))
                cut = shape.intersect(face)
                if cut.Faces():
                    actors(polydata(cut, work, f"cut{k}"), CUT, renderer)
            actors(data, colour, renderer)
            caption.append(f"{files[k]}: colour {k + 1} ({COLOURS[k % 5]})")
        for k, path in enumerate(request.get("keepouts") or []):
            p = Path(path)
            if p.is_absolute() or ".." in p.parts or not p.is_file():
                return {"error": f"query: no file {path} in the part's directory"}
            built = cq.importers.importStep(str(p)).val()
            actors(polydata(built, work, f"keepout{k}"), KEEP_OUT, renderer, opacity=0.3)
        if request.get("keepouts"):
            named = ", ".join(request["keepouts"])
            caption.append(f"translucent red: your keep-outs ({named})")
        if view == "section":
            caption.append(f"cut at {plane['axis']} = {plane['at']}: the cut face in dark grey")
        cam = renderer.GetActiveCamera()
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*centre)
        cam.SetPosition(*[c + 100 * d for c, d in zip(centre, camera[0], strict=True)])
        cam.SetViewUp(*camera[1])
        renderer.ResetCamera()
        cam.Zoom(1.1)
        window.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(window)
        grab.Update()
        from vtk.util.numpy_support import vtk_to_numpy  # noqa: PLC0415

        pixels = vtk_to_numpy(grab.GetOutput().GetPointData().GetScalars())
        # The share of the picture that isn't the white background: a check it drew.
        painted = round(float((pixels[:, :3] < 250).any(axis=1).mean()), 4)
        png = vtk.vtkPNGWriter()
        png.SetWriteToMemory(1)
        png.SetInputConnection(grab.GetOutputPort())
        png.Write()
        data = bytes(memoryview(png.GetResult()))
    return {
        "png": base64.b64encode(data).decode(),
        "view": view,
        "caption": caption,
        "painted": painted,
    }


def main() -> None:
    try:
        found = render(json.loads(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 - whatever fails is said, not raised
        found = {"error": f"{type(exc).__name__}: {exc}"[:400]}
    print(MARK + json.dumps(found))


if __name__ == "__main__":
    main()
