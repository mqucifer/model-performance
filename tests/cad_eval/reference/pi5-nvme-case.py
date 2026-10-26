import cadquery as cq


def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0)
        .translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    )


# Taking each board as 1.6 mm thick (neither drawing says): the Base's bottom at
# 0 - 1.6 - 12 - 1.6 = -15.2.
X0, X1 = -6.0, 92.0  # inside the walls: the Base and the flex cable's loop at -X
Y0, Y1 = -2.0, 58.0
WALL, FLOOR, TOP = 2.0, -24.0, 18.0
HOLES = [(x, y) for x in (3.5, 61.5) for y in (3.5, 52.5)]

body = box(X0 - WALL, X1 + WALL, Y0 - WALL, Y1 + WALL, FLOOR - WALL, TOP).cut(
    box(X0, X1, Y0, Y1, FLOOR, TOP + 1)
)
for x, y in HOLES:
    body = body.union(
        cq.Workplane("XY")
        .workplane(offset=FLOOR)
        .center(x, y)
        .circle(3)
        .circle(1.1)
        .extrude(-15.2 - FLOOR)
    )
# The ports: USB-C and the micro HDMIs through the front, Ethernet and USB through the end.
for x, width in ((11.2, 11), (25.8, 9), (39.2, 9)):
    body = body.cut(box(x - width / 2, x + width / 2, Y0 - WALL - 1, Y0 + 1, -2.5, 6))
for y, width in ((10.2, 17), (29.1, 16), (47, 16)):
    body = body.cut(box(X1 - 1, X1 + WALL + 1, y - width / 2, y + width / 2, -1, 16))

# The lid: a plate on the walls' tops, with a lip inside them, 0.2 mm clear, and vents.
lid = box(X0 - WALL, X1 + WALL, Y0 - WALL, Y1 + WALL, TOP, TOP + 2).union(
    box(X0 + 0.2, X1 - 0.2, Y0 + 0.2, Y1 - 0.2, TOP - 3, TOP).cut(
        box(X0 + 1.7, X1 - 1.7, Y0 + 1.7, Y1 - 1.7, TOP - 4, TOP + 1)
    )
)
for k in range(10):
    lid = lid.cut(box(12, 72, 4 + 5 * k, 7 + 5 * k, TOP - 1, TOP + 3))

cq.exporters.export(body, "base.step")
cq.exporters.export(lid, "lid.step")
