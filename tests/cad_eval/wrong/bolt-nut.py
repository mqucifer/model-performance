import math

import cadquery as cq

# M8x1.25, ISO 68-1's basic profile: 60° flanks, a flat of P/8 at the crest and P/4 at the root.
P = 1.25
H = math.sqrt(3) / 2 * P
R_MAJOR = 4.0
R_MINOR = R_MAJOR - 5 / 8 * H
T30 = math.tan(math.radians(30))
SINK = 0.1  # the profile reaches this far into the core, so the fuse is clean
CLEAR = 0.0  # the nut's thread, bigger by this across its radius


def threaded(z0, z1, grow=0.0):
    """A threaded rod from z0 to z1, its profile `grow` mm out; every turn in one phase."""
    major, minor = R_MAJOR + grow, R_MINOR + grow
    h = major - minor + SINK
    root = P / 16 + h * T30  # the crest's half-flat, P/16, and the 60° flank below it
    profile = (
        cq.Workplane("XZ")
        .polyline([(minor - SINK, -root), (major, -P / 16), (major, P / 16), (minor - SINK, root)])
        .close()
        .wire()
        .val()
    )
    start = P * math.floor(z0 / P) - P
    length = z1 - start + P
    helix = cq.Wire.makeHelix(P, length, minor - SINK, center=cq.Vector(0, 0, start))
    swept = cq.Solid.sweep(profile.translate((0, 0, start)), [], helix, isFrenet=True)
    core = cq.Solid.makeCylinder(minor, length, cq.Vector(0, 0, start))
    return core.fuse(swept).intersect(
        cq.Solid.makeCylinder(major + 0.5, z1 - z0, cq.Vector(0, 0, z0))
    )


def hexagon(z0, z1):
    across_corners = 13 / math.cos(math.radians(30))
    return cq.Workplane("XY").workplane(offset=z0).polygon(6, across_corners).extrude(z1 - z0)


bolt = hexagon(-5.3, 0).union(cq.Workplane().add(threaded(0, 30)))
nut = hexagon(10, 16.5).cut(cq.Workplane().add(threaded(9, 17.5, grow=CLEAR)))
cq.exporters.export(bolt, "bolt.step")
cq.exporters.export(nut, "nut.step")
