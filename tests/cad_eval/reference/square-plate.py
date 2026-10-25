import cadquery as cq

part = (
    cq.Workplane("XY")
    .box(50, 50, 3, centered=(True, True, False))
    .faces(">Z")
    .workplane()
    .pushPoints([(x, y) for x in (20, -20) for y in (20, -20)])
    .hole(3.4)
)
cq.exporters.export(part, "part.step")
