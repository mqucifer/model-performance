import cadquery as cq

# A box with its top face taken away: a shell, not a solid.
box = cq.Workplane("XY").box(10, 10, 10).val()
faces = [f for f in box.Faces() if f.Center().z < 4.9]
cq.exporters.export(cq.Shell.makeShell(faces), "part.step")
