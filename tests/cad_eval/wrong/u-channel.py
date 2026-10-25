import cadquery as cq

profile = (
    cq.Workplane("YZ")
    .polyline([(-15, 0), (15, 0), (15, 20), (13, 20), (13, 3), (-13, 3), (-13, 20), (-15, 20)])
    .close()
    .extrude(60)
)
holes = cq.Workplane("XY").pushPoints([(15, 0), (45, 0)]).circle(2.25).extrude(3)
part = profile.cut(holes)
cq.exporters.export(part, "part.step")
