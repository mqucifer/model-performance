import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0)
        .translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    )


CLEAR = 0.2
cabinet = box(-50, 50, 0, 80, 0, 60).cut(box(-47, 47, -1, 77, 3, 57))
x, y1, z0 = 47 - CLEAR, 77 - CLEAR, 3 + CLEAR
body = box(-x, x, -0.5, y1, z0, 50).cut(box(-x + 2, x - 2, 1.5, y1 - 2, z0 + 2, 51))
front = box(-50, 50, -3.5, -0.5, 0.5, 59.5)
drawer = body.union(front).cut(
    cq.Workplane("XZ", origin=(0, 2, 0)).center(0, 40).circle(10).extrude(6)
)
cq.exporters.export(cabinet, "cabinet.step")
cq.exporters.export(drawer, "drawer.step")
