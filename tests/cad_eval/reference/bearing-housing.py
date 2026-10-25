import cadquery as cq

part = (
    cq.Workplane("XY")
    .box(40, 40, 10, centered=(True, True, False))
    .faces(">Z")
    .workplane()
    .hole(22.1, 8)
    .faces(">Z")
    .workplane()
    .hole(16)
    .faces(">Z")
    .workplane()
    .pushPoints([(x, y) for x in (15, -15) for y in (15, -15)])
    .hole(4.5)
)
cq.exporters.export(part, "part.step")
