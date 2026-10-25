import cadquery as cq

part = cq.Workplane("XY").circle(9).circle(4.1).extrude(10)
screw = cq.Workplane("YZ").workplane(offset=3).center(0, 5).circle(1.25).extrude(7)
part = part
cq.exporters.export(part, "part.step")
