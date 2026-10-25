import cadquery as cq

base = cq.Workplane("XY").box(50, 40, 4, centered=(False, True, False))
upright = cq.Workplane("XY").box(4, 40, 50, centered=(False, True, False))
part = (
    base.union(upright).edges("|Y").edges(cq.selectors.NearestToPointSelector((4, 0, 4))).fillet(5)
)
part = part.cut(cq.Workplane("XY").pushPoints([(35, 10), (35, -10)]).circle(2.75).extrude(4))
part = part.cut(cq.Workplane("YZ").pushPoints([(10, 35), (-10, 35)]).circle(2.75).extrude(4))
cq.exporters.export(part, "part.step")
