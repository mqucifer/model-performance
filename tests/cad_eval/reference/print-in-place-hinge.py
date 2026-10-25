import cadquery as cq


def along_y(radius, y0, y1, hole=0.0):
    tube = cq.Workplane("XZ").workplane(offset=-y1).circle(radius)
    if hole:
        tube = tube.circle(hole)
    return tube.extrude(y1 - y0)


def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0)
        .translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    )


a = box(-25, -3.3, -15, 15, -1.5, 1.5)
for y0, y1 in ((-15, -5.15), (5.15, 15)):
    a = a.union(along_y(3, y0, y1)).union(box(-3.3, -2, y0, y1, -1.5, 1.5))
a = a.union(along_y(1.5, -15, 15))
b = (
    box(3.3, 25, -15, 15, -1.5, 1.5)
    .union(along_y(3, -4.85, 4.85, hole=1.8))
    .union(box(2, 3.3, -4.85, 4.85, -1.5, 1.5))
)
cq.exporters.export(a.add(b), "part.step")
