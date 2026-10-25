import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(
        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    )


DEPTH = 0.15
shell = box(-30, 30, -20, 20, 0, 30).cut(box(-28, 28, -18, 18, 2, 31))
windows = box(-31, -27, -6, 6, 21, 25).union(box(27, 31, -6, 6, 21, 25))
lid = box(-31.8, 31.8, -20, 20, 30, 32)
for side in (1, -1):
    arm = box(30.2, 31.8, -5, 5, 20, 30)
    hook = (
        cq.Workplane("XZ")
        .polyline([(30.2, 24.8), (30.2 - DEPTH, 24.8), (30.2, 21.8)])
        .close()
        .extrude(5, both=True)
    )
    part = arm.union(hook)
    lid = lid.union(part if side == 1 else part.mirror("YZ"))
cq.exporters.export(shell.cut(windows), "box.step")
cq.exporters.export(lid, "lid.step")
