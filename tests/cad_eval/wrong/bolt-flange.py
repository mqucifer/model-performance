import cadquery as cq

part = (
    cq.Workplane("XY")
    .circle(40)
    .circle(15)
    .extrude(6)
    .faces(">Z")
    .workplane()
    .polarArray(30, 30, 360, 6)
    .hole(6.5)
)
cq.exporters.export(part, "part.step")
