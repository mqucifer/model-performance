import cadquery as cq

BORE = 8.3
shaft = cq.Workplane("XY").workplane(offset=-10).circle(4).extrude(60)
bushing = (
    cq.Workplane("XY")
    .circle(9)
    .extrude(2)
    .union(cq.Workplane("XY").workplane(offset=2).circle(6).extrude(10))
    .cut(cq.Workplane("XY").circle(BORE / 2).extrude(12))
)
collar = (
    cq.Workplane("XY")
    .workplane(offset=12.3)
    .circle(9)
    .circle(BORE / 2)
    .extrude(8)
    .cut(cq.Workplane("YZ").workplane(offset=3).center(0, 16.3).circle(1.25).extrude(7))
)
cq.exporters.export(shaft, "shaft.step")
cq.exporters.export(bushing, "bushing.step")
cq.exporters.export(collar, "collar.step")
