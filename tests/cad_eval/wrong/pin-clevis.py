import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(
        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    )


def along_y(diameter, y0, y1, z=18.0):
    return cq.Workplane("XZ", origin=(0, y1, 0)).center(0, z).circle(diameter / 2).extrude(y1 - y0)


HOLE = 6.05
clevis = (
    box(-8, 8, -9, 9, 0, 6)
    .union(box(-8, 8, -9, -5, 6, 26))
    .union(box(-8, 8, 5, 9, 6, 26))
    .cut(along_y(HOLE, -10, 10))
)
tongue = box(-6, 6, -4.6, 4.6, 10, 40).cut(along_y(HOLE, -5, 5))
pin = along_y(6, -10, 10).union(along_y(10, -12, -10))
cq.exporters.export(clevis, "clevis.step")
cq.exporters.export(tongue, "tongue.step")
cq.exporters.export(pin, "pin.step")
