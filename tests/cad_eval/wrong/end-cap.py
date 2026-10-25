import cadquery as cq

part = cq.Workplane("XY").circle(8).extrude(12).faces("<Z").workplane().hole(10, 8)
cq.exporters.export(part, "part.step")
