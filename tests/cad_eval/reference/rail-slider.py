import cadquery as cq

body = cq.Workplane("XY").box(30, 30, 15, centered=(True, True, False))
part = body.cut(cq.Workplane("XY").box(30, 20.4, 10.2, centered=(True, True, False)))
cq.exporters.export(part, "part.step")
