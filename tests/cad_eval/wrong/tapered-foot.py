import cadquery as cq

part = (
    cq.Workplane("XY")
    .rect(40, 40)
    .workplane(offset=30)
    .rect(30, 30)
    .loft(ruled=True)
    .faces(">Z")
    .workplane()
    .hole(6.5)
)
cq.exporters.export(part, "part.step")
