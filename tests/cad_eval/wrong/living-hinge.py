import cadquery as cq

flaps = (
    cq.Workplane("XY").center(-17, 0).rect(30, 20).extrude(3)
    .union(cq.Workplane("XY").center(17, 0).rect(30, 20).extrude(3))
)
web = cq.Workplane("XY").rect(4.2, 20).extrude(0.6)
cq.exporters.export(flaps.union(web), "part.step")
