import math

import cadquery as cq

# Planted wrong: M8x1.25 with the right pitch and diameters but the wrong flank profile.
P, L = 1.25, 20.0
H = math.sqrt(3) / 2 * P
R_MAJOR = 4.0
R_MINOR = R_MAJOR - 5 / 8 * H
T30 = math.tan(math.radians(30))
SINK = 0.1  # the profile reaches this far into the core, so the fuse is clean


def thread(length: float) -> cq.Solid:
    profile = (
        cq.Workplane("XZ")
        .polyline(
            [
                (R_MINOR - SINK, -0.6 - SINK * 0.92),
                (R_MAJOR, 0.0),
                (R_MINOR - SINK, 0.6 + SINK * 0.92),
            ]
        )
        .close()
        .wire()
        .val()
    )
    helix = cq.Wire.makeHelix(P, length + 2 * P, R_MINOR - SINK, center=cq.Vector(0, 0, -P))
    swept = cq.Solid.sweep(profile.translate((0, 0, -P)), [], helix, isFrenet=True)
    core = cq.Solid.makeCylinder(R_MINOR, length + 2 * P, cq.Vector(0, 0, -P))
    return core.fuse(swept).intersect(cq.Solid.makeCylinder(R_MAJOR + 0.5, length))


head = (
    cq.Workplane("XY")
    .workplane(offset=-5.3)
    .polygon(6, 13 / math.cos(math.radians(30)))
    .extrude(5.3)
)
bolt = head.union(cq.Workplane().add(thread(L)))
cq.exporters.export(bolt, "part.step")
