import cadquery as cq

flange = cq.Workplane("XY").circle(10).extrude(3)
body = cq.Workplane("XY").workplane(offset=3).circle(6).extrude(12)
part = flange.union(body).cut(cq.Workplane("XY").circle(4).extrude(15))
cq.exporters.export(part, "part.step")
