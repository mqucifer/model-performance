import cadquery as cq

outer = cq.Workplane("XY").circle(25).extrude(40)
part = outer.cut(cq.Workplane("XY").workplane(offset=3).circle(23).extrude(37))
cq.exporters.export(part, "part.step")
