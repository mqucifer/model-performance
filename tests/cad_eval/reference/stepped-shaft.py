import cadquery as cq

part = (
    cq.Workplane("XY")
    .circle(10)
    .extrude(10)
    .faces(">Z")
    .workplane()
    .circle(7)
    .extrude(20)
    .faces(">Z")
    .workplane()
    .circle(4)
    .extrude(10)
    .faces(">Z")
    .edges()
    .chamfer(1)
)
cq.exporters.export(part, "part.step")
