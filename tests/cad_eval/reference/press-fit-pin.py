import cadquery as cq

pin = cq.Workplane("XY").circle(2.55).extrude(16).edges("%CIRCLE").chamfer(0.5)
cq.exporters.export(pin, "part.step")
