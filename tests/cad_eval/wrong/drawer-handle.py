import cadquery as cq

path = (
    cq.Workplane("XZ")
    .moveTo(-40, 0)
    .lineTo(-40, 20)
    .radiusArc((-30, 30), 10)
    .lineTo(30, 30)
    .radiusArc((40, 20), 10)
    .lineTo(40, 0)
)
part = cq.Workplane("XY").workplane().center(-40, 0).circle(3).sweep(path, transition="round")
cq.exporters.export(part, "part.step")
