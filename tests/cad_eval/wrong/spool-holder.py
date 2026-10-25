import cadquery as cq

SPINDLE = 27
back = cq.Workplane("XY").box(5, 50, 80, centered=(False, True, True))
spindle = cq.Workplane("YZ").circle(SPINDLE).extrude(85)
cap = cq.Workplane("YZ").workplane(offset=85).circle(30).extrude(3)
holes = cq.Workplane("YZ").pushPoints([(0, 30), (0, -30)]).circle(2.25).extrude(6)
cq.exporters.export(back.union(spindle).union(cap).cut(holes), "part.step")
