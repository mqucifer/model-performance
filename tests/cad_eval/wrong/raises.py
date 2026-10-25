import cadquery as cq

cq.Workplane("XY").box(10, 10, 10).edges().fillet(20)
cq.exporters.export(cq.Workplane("XY").box(10, 10, 10), "part.step")
