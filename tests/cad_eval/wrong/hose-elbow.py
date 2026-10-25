import cadquery as cq

path = cq.Workplane("XZ").lineTo(0, 15).radiusArc((20, 35), 20).lineTo(35, 35)
part = cq.Workplane("XY").circle(5).circle(3.0).sweep(path, transition="round")
cq.exporters.export(part, "part.step")
