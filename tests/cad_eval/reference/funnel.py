import cadquery as cq

profile = [(6, 0), (7.5, 0), (7.5, 10), (31.5, 40), (30, 40), (6, 10)]
part = cq.Workplane("XZ").polyline(profile).close().revolve(360, (0, 0, 0), (0, 1, 0))
cq.exporters.export(part, "part.step")
