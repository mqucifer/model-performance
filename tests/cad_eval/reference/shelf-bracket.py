import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0)
        .translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    )


THICK = 6
back = box(0, 5, -12, 12, -70, 0)
arm = box(0, 120, -4, 4, -THICK, 0)
gusset = (
    cq.Workplane("XZ").polyline([(5, -70), (5, -THICK), (90, -THICK)]).close().extrude(2, both=True)
)
holes = cq.Workplane("YZ").pushPoints([(8, -25), (-8, -55)]).circle(2.25).extrude(6)
cq.exporters.export(back.union(arm).union(gusset).cut(holes), "part.step")
