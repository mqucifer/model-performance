import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0)
        .translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    )


THICK = 3
back = box(0, 5, -25, 25, -40, 40)
arm = box(0, 45, -22, 22, -THICK, 0)
lip = box(40, 45, -22, 22, 0, 12)
holes = cq.Workplane("YZ").pushPoints([(0, 28), (0, -28)]).circle(2.25).extrude(6)
cq.exporters.export(back.union(arm).union(lip).cut(holes), "part.step")
