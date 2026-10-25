# Raspberry Pi 5 case with an NVMe Base Duo

Can you make me a case I can print for my Raspberry Pi 5? It has a Pimoroni NVMe Base Duo mounted under it, with two 2280 SSDs. I want every port the Pi uses reachable, the boards not touching the walls, enough venting to keep them cool, and a lid that comes off without tools.

**The files:** the case's body as `base.step` and its lid as `lid.step`, placed as assembled with the boards in it.

**What I know about the boards** (from Raspberry Pi's mechanical drawing of the Pi 5, and Pimoroni's drawing of the NVMe Base Duo):
- **The Pi 5:** 85 by 56 mm. Its four mounting holes are 2.7 mm across, on a 58 by 49 mm rectangle, each 3.5 mm in from the corner along both edges.
  - On one long edge: the USB-C power socket, centred 11.2 mm from the short edge by the holes, and the two micro HDMI sockets, centred at 25.8 and 39.2 mm. The USB-C's top is 3.2 mm above the board's top face, the micro HDMIs' 3.4 mm.
  - On the short edge across from the holes' side: the Ethernet socket, centred 10.2 mm from that long edge, and the two pairs of USB sockets, centred at 29.1 and 47 mm. They stick out 3 mm past the board's edge.
  - Nothing on its top is taller than 4.4 mm except the Ethernet and USB sockets, the GPIO header and anything plugged in.
  - The PCIe flex cable plugs in on the other short edge.
- **The NVMe Base Duo:** under the Pi on the kit's 12 mm standoffs, its holes on the same 58 by 49 mm pattern. It's 87.6 mm along the Pi's length: its holes are 4.5 mm in from its edge on the flex cable's side, so it sticks out 1 mm past the Pi there, and 1.6 mm past it at the other end. Its holes are 3.5 mm in from the same long edge as the Pi's. The SSDs sit on its top, between it and the Pi. Its flex cable connector is on its top, by its edge on the Pi's flex cable side, centred 29.89 mm from that long edge. The cable runs from there round the boards' edge and up to the Pi.
- Neither drawing gives the boards' thickness.

**So it can be checked:** the Pi's top face is the plane Z = 0, with the board from X = 0 to 85 and Y = 0 to 56. The USB-C and micro HDMI edge is Y = 0, the flex cable's edge is X = 0, and the Ethernet and USB edge is X = 85. So the holes are at X = 3.5 and 61.5, Y = 3.5 and 52.5, and the NVMe Base Duo is below, from X = -1 to 86.6, its top face 12 mm under the Pi's bottom face.
