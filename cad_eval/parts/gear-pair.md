# Gear pair on a plate

**Purpose:** two meshing spur gears turning on posts on a base plate, as in a small gearbox: three parts, printed separately and assembled.

**The files:** `plate.step`, `gear-a.step` and `gear-b.step`, each placed as assembled.

**Size:**
- **The gears:** module 1.5, a 20° pressure angle, the standard full-depth involute profile (an addendum of one module, a dedendum of 1.25), 6 mm thick. Gear A has 12 teeth, gear B 28. Each has a 5.4 mm bore.
- **Their centres:** 30.2 mm apart: the standard 30 mm and 0.2 mm more, for backlash. Gear A on the Z axis, gear B's axis at X = 30.2, Y = 0.
- **Plate:** from X = -12 to 58, Y = -25 to 25, Z = 0 to 4, with a post 5 mm across standing up under each gear, from Z = 4 to 14.
- **The gears** sit on their posts 0.5 mm above the plate, from Z = 4.5 to 10.5. Gear A has a tooth centred on +X, pointing at gear B, and gear B is turned so that a gap between its teeth faces it: they mesh.

**Tolerance:** the gears mustn't overlap each other or the plate, and mesh: their closest distance, tooth to tooth, between 0.02 and 0.3 mm. ±0.05 mm on the bores and posts, so each gear's clearance on its post is 0.15 to 0.25 mm. Each tooth's width within about 0.1 mm of the involute's; ±0.1 mm on everything else.

**Placement:** as assembled, as above.
