import cadquery as cq

part = (
    cq.Workplane("XY")
    .box(80, 12, 5, centered=(True, True, False))
    .cut(cq.Workplane("XY").slot2D(30, 5.5).extrude(5))
)
cq.exporters.export(part, "part.step")
