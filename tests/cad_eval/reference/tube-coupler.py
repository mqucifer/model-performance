import cadquery as cq

sleeve = cq.Workplane("XY").workplane(offset=-15).circle(7).circle(5.1).extrude(30)
stop = cq.Workplane("XY").workplane(offset=-0.5).circle(5.1).circle(3.5).extrude(1)
part = sleeve.union(stop)
cq.exporters.export(part, "part.step")
