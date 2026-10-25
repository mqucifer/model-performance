import cadquery as cq

part = cq.Workplane("XY").box(60, 40, 30, centered=(True, True, False)).faces(">Z").shell(-2)
slots = (
    cq.Workplane("XY")
    .pushPoints([(x, 0) for x in (-16, -8, 0, 8, 16)])
    .slot2D(30, 3, angle=90)
    .extrude(2)
)
part = part.cut(slots)
cq.exporters.export(part, "part.step")
