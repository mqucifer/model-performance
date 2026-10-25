import cadquery as cq

base = cq.Workplane("XY").box(40, 40, 3, centered=(True, True, False))
fins = (
    cq.Workplane("XY")
    .workplane(offset=3)
    .pushPoints([(x, 0) for x in range(-18, 13, 6)])
    .rect(1.5, 40)
    .extrude(15)
)
part = base.union(fins)
cq.exporters.export(part, "part.step")
