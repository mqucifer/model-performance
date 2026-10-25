import cadquery as cq

plate = cq.Workplane("XY").workplane(offset=30).rect(60, 40).extrude(2)
lip = cq.Workplane("XY").workplane(offset=26).rect(55.6, 35.6).rect(55.6 - 3, 35.6 - 3).extrude(4)
cq.exporters.export(plate.union(lip), "part.step")
