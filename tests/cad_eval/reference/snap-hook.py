import cadquery as cq

base = cq.Workplane("XY").box(10, 8, 4, centered=(True, True, False))
beam = cq.Workplane("XY").workplane(offset=4).center(4.2, 0).rect(1.6, 8).extrude(16)
hook = (
    cq.Workplane("XZ").polyline([(5, 17), (6, 17), (5, 20)]).close().extrude(4, both=True)
)
cq.exporters.export(base.union(beam).union(hook), "part.step")
