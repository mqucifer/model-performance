import math

import cadquery as cq

M, PRESSURE = 1.5, math.radians(20)


def inv(a):
    return math.tan(a) - a


def gear(z, turn=0.0):
    """An involute spur gear's outline, with a tooth centred on angle `turn`."""
    pitch = z * M / 2
    base, tip, root = pitch * math.cos(PRESSURE), pitch + M, pitch - 1.25 * M

    def half(r):
        return math.pi / (2 * z) + inv(PRESSURE) - inv(math.acos(min(1.0, base / max(r, base))))

    def polar(r, a):
        return (r * math.cos(a), r * math.sin(a))

    step = 2 * math.pi / z
    points = []
    low = max(base, root)
    flank = [low + (tip - low) * i / 24 for i in range(25)]
    for k in range(z):
        c = turn + k * step
        points.append(polar(root, c - half(low)))
        points += [polar(r, c - half(r)) for r in flank]
        points += [polar(tip, c - half(tip) + 2 * half(tip) * i / 4) for i in range(1, 4)]
        points += [polar(r, c + half(r)) for r in reversed(flank)]
        points.append(polar(root, c + half(low)))
        gap = step - 2 * half(low)
        points += [polar(root, c + half(low) + gap * i / 6) for i in range(1, 6)]
    return points


CENTRES = 30.2
a = (
    cq.Workplane("XY").workplane(offset=4.5).polyline(gear(12)).close().extrude(6)
    .faces(">Z").workplane().hole(5.4)
)
b = (
    cq.Workplane("XY").workplane(offset=4.5).polyline(gear(28)).close().extrude(6)
    .faces(">Z").workplane().hole(5.4)
    .translate((CENTRES, 0, 0))
)
plate = (
    cq.Workplane("XY").box(70, 50, 4, centered=False).translate((-12, -25, 0))
    .union(cq.Workplane("XY").workplane(offset=4).pushPoints([(0, 0), (CENTRES, 0)]).circle(2.5).extrude(10))
)
cq.exporters.export(plate, "plate.step")
cq.exporters.export(a, "gear-a.step")
cq.exporters.export(b, "gear-b.step")
