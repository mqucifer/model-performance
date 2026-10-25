import math

import cadquery as cq

Z, M, PRESSURE = 20, 1.5, math.radians(20)
PITCH = Z * M / 2
BASE = PITCH * math.cos(PRESSURE)
TIP = PITCH + M
ROOT = PITCH - 1.25 * M


def inv(a):
    return math.tan(a) - a


def half(r):
    """Straight flanks from the base circle to the tip: no involute."""
    lo, hi = math.pi / (2 * Z) + inv(PRESSURE), math.pi / (2 * Z) + inv(PRESSURE) - inv(math.acos(BASE / TIP))
    return lo + (hi - lo) * (max(r, BASE) - BASE) / (TIP - BASE)


def polar(r, a):
    return (r * math.cos(a), r * math.sin(a))


points = []
pitch_angle = 2 * math.pi / Z
for k in range(Z):
    c = k * pitch_angle
    flank = [BASE + (TIP - BASE) * i / 24 for i in range(25)]
    points.append(polar(ROOT, c - half(BASE)))
    points += [polar(r, c - half(r)) for r in flank]
    points += [polar(TIP, c - half(TIP) + 2 * half(TIP) * i / 4) for i in range(1, 4)]
    points += [polar(r, c + half(r)) for r in reversed(flank)]
    points.append(polar(ROOT, c + half(BASE)))
    gap = pitch_angle - 2 * half(BASE)
    points += [polar(ROOT, c + half(BASE) + gap * i / 6) for i in range(1, 6)]
gear = cq.Workplane("XY").polyline(points).close().extrude(8).faces(">Z").workplane().hole(6)
cq.exporters.export(gear, "part.step")
