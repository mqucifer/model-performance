import cadquery as cq

part = cq.Workplane("XY").circle(6).circle(5.3 / 2).extrude(10)
cq.exporters.export(part, "part.step")
