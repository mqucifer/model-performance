import cadquery as cq

part = (
    cq.Workplane("XY")
    .box(60, 40, 3, centered=(True, True, False))
    .faces(">Z")
    .workplane()
    .rarray(10, 10, 4, 3)
    .hole(5)
)
cq.exporters.export(part, "part.step")
