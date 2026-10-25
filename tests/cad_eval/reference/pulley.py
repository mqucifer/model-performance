import cadquery as cq

profile = [(4, 0), (20, 0), (20, 3), (16, 6), (20, 9), (20, 12), (4, 12)]
part = cq.Workplane("XZ").polyline(profile).close().revolve(360, (0, 0, 0), (0, 1, 0))
cq.exporters.export(part, "part.step")
