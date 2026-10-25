import math

import cadquery as cq

helix = cq.Wire.makeHelix(pitch=5, height=20, radius=10)
tangent = cq.Vector(0, 2 * math.pi * 10, 5).normalized()
plane = cq.Plane(origin=(10, 0, 0), xDir=(1, 0, 0), normal=tangent)
part = cq.Workplane(plane).circle(1).sweep(cq.Workplane().add(helix), isFrenet=True)
cq.exporters.export(part, "part.step")
