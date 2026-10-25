import cadquery as cq

plate = cq.Workplane("XY").workplane(offset=30).rect(60, 40).extrude(2)
lip = cq.Workplane("XY").workplane(offset=26).rect(56.2, 36.2).rect(56.2 - 3, 36.2 - 3).extrude(4)
cq.exporters.export(plate.union(lip), "part.step")
