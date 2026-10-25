import cadquery as cq

# A round bore: it slips on the flat.
knob = cq.Workplane("XY").workplane(offset=1).circle(15).extrude(16)
bore = cq.Workplane("XY").circle(3.05).extrude(12.5)
cq.exporters.export(knob.cut(bore), "part.step")
