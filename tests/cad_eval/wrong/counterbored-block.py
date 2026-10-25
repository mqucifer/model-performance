import cadquery as cq

part = (
    cq.Workplane("XY")
    .box(40, 20, 15, centered=(True, True, False))
    .faces(">Z")
    .workplane()
    .pushPoints([(12, 0), (-12, 0)])
    .hole(4.5)
)
cq.exporters.export(part, "part.step")
