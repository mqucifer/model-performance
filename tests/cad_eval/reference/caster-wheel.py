import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(
        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    )


def along_y(diameter, y0, y1, bore=0.0):
    tube = cq.Workplane("XZ", origin=(0, y1, 0)).circle(diameter / 2)
    if bore:
        tube = tube.circle(bore / 2)
    return tube.extrude(y1 - y0)


BORE = 5.3
axle = along_y(5, -14, 14)
wheel = along_y(40, -6, 6, BORE)
spacer_a = along_y(9, -9, -6.3, BORE)
spacer_b = along_y(9, 6.3, 9, BORE)
fork = (
    box(-8, 8, -13.3, -9.3, -8, 26)
    .union(box(-8, 8, 9.3, 13.3, -8, 26))
    .union(box(-12, 12, -13.3, 13.3, 26, 30))
    .cut(along_y(BORE, -14, 14))
)
for name, part in (
    ("axle", axle), ("wheel", wheel), ("spacer-a", spacer_a), ("spacer-b", spacer_b), ("fork", fork)
):
    cq.exporters.export(part, f"{name}.step")
