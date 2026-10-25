import cadquery as cq

shank = cq.Workplane("XY").circle(9.9).extrude(5)
head = cq.Workplane("XY").workplane(offset=5).circle(13).extrude(2)
part = shank.union(head)
cq.exporters.export(part, "part.step")
