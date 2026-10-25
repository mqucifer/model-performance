import cadquery as cq

tray = cq.Workplane("XY").box(80, 60, 20, centered=(True, True, False)).faces(">Z").shell(-2)
divider = cq.Workplane("XY").box(2, 58, 20, centered=(True, True, False))
part = tray.union(divider)
cq.exporters.export(part, "part.step")
