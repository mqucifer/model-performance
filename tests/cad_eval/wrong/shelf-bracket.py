import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0)
        .translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    )


# No gusset, and a thin arm: it looks like a bracket but bends.
back = box(0, 5, -12, 12, -70, 0)
arm = box(0, 120, -4, 4, -3, 0)
holes = cq.Workplane("YZ").pushPoints([(8, -25), (-8, -55)]).circle(2.25).extrude(6)
cq.exporters.export(back.union(arm).cut(holes), "part.step")
