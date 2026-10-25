import cadquery as cq

block = cq.Workplane("XY").workplane(offset=5.2).rect(30, 24).extrude(9.8)
# The tongue's flanks offset 0.2 mm square to themselves, cut by the block's bottom and the
# tongue's top raised 0.2 mm.
low, high = 5.2954, 7.2954
groove = (
    cq.Workplane("YZ").polyline([(-low, 5.2), (low, 5.2), (high, 10.2), (-high, 10.2)])
    .close().extrude(15, both=True)
)
cq.exporters.export(block.cut(groove), "part.step")
