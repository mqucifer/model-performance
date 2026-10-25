import cadquery as cq

part = cq.Workplane("XY").polygon(6, 16 / 3**0.5).circle(1.6).extrude(15)
cq.exporters.export(part, "part.step")
