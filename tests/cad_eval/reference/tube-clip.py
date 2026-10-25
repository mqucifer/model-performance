import cadquery as cq

BORE = 10.1  # the tube's 10 mm radius and a little
pad = cq.Workplane("XY").box(12, 30, 8, centered=(True, True, False)).translate((0, 0, -8))
ring = cq.Workplane("YZ").center(0, -20).circle(13).circle(BORE).extrude(6, both=True)
# The opening, 100° wide, facing down: narrower than the tube, so it snaps in.
opening = (
    cq.Workplane("YZ")
    .center(0, -20)
    .polyline([(0, 0), (20 * 0.766, -20 * 0.643 * 1.4), (-20 * 0.766, -20 * 0.643 * 1.4)])
    .close()
    .extrude(7, both=True)
)
holes = cq.Workplane("XY").pushPoints([(0, -11), (0, 11)]).circle(2.25).extrude(-9)
clip = (
    pad.union(ring)
    .cut(opening)
    .cut(cq.Workplane("YZ").center(0, -20).circle(BORE).extrude(7, both=True))
    .cut(holes)
)
cq.exporters.export(clip, "part.step")
