import cadquery as cq

part = (
    cq.Workplane("XY")
    .box(60, 60, 4, centered=(True, True, False))
    .edges("|Z")
    .fillet(5)
    .faces(">Z")
    .workplane()
    .hole(22)
    .pushPoints([(x, y) for x in (15.5, -15.5) for y in (15.5, -15.5)])
    .hole(3.4)
)
cq.exporters.export(part, "part.step")
