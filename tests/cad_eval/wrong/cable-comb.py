import cadquery as cq

SLOTS = (-20, -10, 0, 10, 20)
comb = cq.Workplane("XY").box(10, 60, 18, centered=(True, True, False))
for y in SLOTS:
    # 5.3 mm wide, open at the top, its round bottom under the cable's centre.
    slot = (
        cq.Workplane("YZ")
        .center(y, 10)
        .circle(2.65)
        .extrude(6, both=True)
        .union(
            cq.Workplane("XY").box(12, 5.3, 9, centered=(True, True, False)).translate((0, y, 10))
        )
    )
    comb = comb.cut(slot)
cq.exporters.export(comb, "part.step")
