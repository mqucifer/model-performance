import cadquery as cq

pin = cq.Workplane("XY").circle(2.5).extrude(16).edges("%CIRCLE").chamfer(0.5)
cq.exporters.export(pin, "part.step")
