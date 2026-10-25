import cadquery as cq

knob = cq.Workplane("XY").workplane(offset=1).circle(15).extrude(16)
# Flutes round the rim to grip.
for k in range(12):
    knob = knob.cut(
        cq.Workplane("XY")
        .workplane(offset=1)
        .center(0, 0)
        .transformed(rotate=(0, 0, 30 * k))
        .center(15.5, 0)
        .circle(1.5)
        .extrude(16)
    )
# The D bore, snug: 0.05 mm over the shaft's round and its flat, to Z = 12.5.
bore = (
    cq.Workplane("XY")
    .workplane(offset=0)
    .circle(3.05)
    .extrude(12.5)
    .cut(
        cq.Workplane("XY").box(10, 10, 12.5, centered=(False, True, False)).translate((1.55, 0, 0))
    )
)
cq.exporters.export(knob.cut(bore), "part.step")
