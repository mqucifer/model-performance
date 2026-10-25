import cadquery as cq

part = cq.Workplane("XY").circle(10).circle(10.5 / 2).extrude(2)
cq.exporters.export(part, "part.step")
