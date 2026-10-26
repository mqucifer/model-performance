"""A dimensioned plan before code, checked against what the spec states.

mqucifer/model-performance#30. In the `refs-plan` arm the model writes a plan with
the `plan` tool before any `write`: its parts, the interfaces between them, the key
sizes with their source, and how the parts fit. The plan is checked here against the
values each case's spec states in its own text (`STATED`), by value on the right part,
whatever the model calls the size: a plan that misses one goes back with the miss named
in the spec's words. Every miss is logged with the plan's sizes it was checked against.

The guard: only numbers the spec's text gives are checked. Never the case's probes,
bounds or volumes: those stay the evaluation's, and the miss names only what the
model was already told. Sizes the model chooses (a worded case's wall, a knob's grip)
are recorded, not judged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# After this many plans that miss, the gate opens anyway, so a run isn't spent on plans.
ATTEMPTS = 3
SOURCES = ("spec", "reference", "chosen")
FITS = ("clearance", "interference", "contact")


@dataclass(frozen=True)
class Stated:
    """One value a spec states: the part it's on (None: any part), the spec's words for
    it (for the miss message only), its value and the spec's tolerance."""

    part: str | None
    what: str
    value: float
    tol: float = 0.1


def s(part: str | None, what: str, value: float, tol: float = 0.1) -> Stated:
    return Stated(part, what, value, tol)


STATED: dict[str, tuple[Stated, ...]] = {
    "living-hinge": (
        s(None, "each flap's length along X", 30),
        s(None, "each flap's width along Y", 20),
        s(None, "each flap's thickness", 3),
        s(None, "the gap between the flaps", 4),
        s(None, "the web's thickness", 0.4, 0.05),
    ),
    "press-fit-pin": (
        s(None, "the pin's diameter", 5.10, 0.02),
        s(None, "the pin's length", 16),
        s(None, "the chamfer", 0.5),
        s(None, "the interference", 0.10, 0.02),
    ),
    "snap-hook": (
        s(None, "the base's length along X", 10),
        s(None, "the base's width along Y", 8),
        s(None, "the base's height", 4),
        s(None, "the beam's thickness", 1.6, 0.05),
        s(None, "the beam's height above the base", 16),
        s(None, "the hook's overhang", 1.0, 0.05),
        s(None, "the catch's depth below the beam's top", 3),
        s(None, "the gap to the panel", 0.1, 0.05),
    ),
    "dovetail-slider": (
        s(None, "the block's length along X", 30),
        s(None, "the block's width along Y", 24),
        s(None, "the block's top", 15),
        s(None, "the clearance on every face", 0.2, 0.05),
    ),
    "print-in-place-hinge": (
        s(None, "the plates' thickness", 3),
        s(None, "the knuckles' outside diameter", 6),
        s(None, "the pin's diameter", 3, 0.05),
        s(None, "the bore's diameter", 3.6, 0.05),
        s(None, "the clearance where the leaves meet", 0.3, 0.05),
    ),
    "spur-gear": (
        s(None, "the number of teeth", 20, 0),
        s(None, "the module", 1.5, 0),
        s(None, "the pressure angle", 20, 0),
        s(None, "the pitch diameter", 30),
        s(None, "the tip diameter", 33),
        s(None, "the root diameter", 26.25),
        s(None, "the face width", 8),
        s(None, "the bore", 6, 0.05),
    ),
    "m8-bolt": (
        s(None, "the head's width across the flats", 13),
        s(None, "the head's height", 5.3),
        s(None, "the shank's length", 20),
        s(None, "the crest diameter", 8, 0.2),
        s(None, "the pitch", 1.25, 0),
        s(None, "the root diameter", 6.65, 0.2),
    ),
    "pin-clevis": (
        s("clevis", "the cheeks' height, to Z = 26", 26),
        s("clevis", "each cheek's thickness", 4),
        s("clevis", "the pin hole's diameter", 6.3, 0.05),
        s("tongue", "the tongue's thickness", 9.2),
        s("tongue", "the tongue's hole diameter", 6.3, 0.05),
        s("pin", "the pin's diameter", 6, 0.05),
        s("pin", "the head's diameter", 10),
        s(None, "the tongue's gap to each cheek", 0.4, 0.1),
    ),
    "shaft-bushing-collar": (
        s("shaft", "the shaft's diameter", 8, 0.05),
        s("bushing", "the flange's diameter", 18),
        s("bushing", "the sleeve's diameter", 12),
        s("bushing", "the bore", 8.3, 0.05),
        s("collar", "the collar's diameter", 18),
        s("collar", "the collar's bore", 8.3, 0.05),
        s("collar", "the set screw hole", 2.5),
        s(None, "the collar's gap to the bushing", 0.3, 0.05),
    ),
    "drawer-cabinet": (
        s("cabinet", "the cabinet's width along X", 100),
        s("cabinet", "the cabinet's depth", 80),
        s("cabinet", "the cabinet's height", 60),
        s("cabinet", "the cabinet's walls", 3),
        s("drawer", "the drawer's walls", 2),
        s("drawer", "the finger hole's diameter", 20),
        s(None, "the drawer's gap to the cabinet", 0.5, 0.1),
    ),
    "gear-pair": (
        s("gear-a", "gear A's teeth", 12, 0),
        s("gear-b", "gear B's teeth", 28, 0),
        s(None, "the module", 1.5, 0),
        s(None, "the pressure angle", 20, 0),
        s(None, "the gears' thickness", 6),
        s(None, "the gears' bore", 5.4, 0.05),
        s(None, "the centre distance", 30.2, 0.05),
        s("plate", "the posts' diameter", 5, 0.05),
    ),
    "bolt-nut": (
        s("bolt", "the head's width across the flats", 13),
        s("bolt", "the head's height", 5.3),
        s("bolt", "the shank's length", 30),
        s("bolt", "the crest diameter", 8, 0.2),
        s(None, "the pitch", 1.25, 0),
        s("bolt", "the root diameter", 6.65, 0.2),
        s("nut", "the nut's width across the flats", 13),
        s("nut", "the nut's thickness", 6.5),
        s(None, "the thread clearance", 0.15, 0.05),
    ),
    "snap-enclosure": (
        s("box", "the box's length along X", 60),
        s("box", "the box's width along Y", 40),
        s("box", "the box's height", 30),
        s("box", "the walls", 2),
        s("box", "the windows' width", 12),
        s("lid", "the lid's thickness", 2),
        s("lid", "the arms' thickness", 1.6, 0.05),
        s("lid", "the hooks' depth", 1.0, 0.05),
        s(None, "the arms' clearance to the wall", 0.2, 0.05),
    ),
    "caster-wheel": (
        s("axle", "the axle's diameter", 5, 0.05),
        s("wheel", "the wheel's diameter", 40),
        s("wheel", "the wheel's width", 12),
        s("wheel", "the wheel's bore", 5.3, 0.05),
        s("spacer-a", "the spacers' outside diameter", 9),
        s("fork", "the arms' thickness", 4),
        s("fork", "the axle holes", 5.3, 0.05),
        s(None, "the gaps between wheel, spacers and fork", 0.3, 0.05),
    ),
    # The worded cases: only what their text states. Every other size is chosen.
    "shelf-bracket": (
        s(None, "the screws' size", 4, 0.6),
        s(None, "the reach under the shelf: at least 100 mm, at most the board's 150", 125, 25),
    ),
    "tube-clip": (
        s(None, "the tube's diameter", 20, 0.6),
        s(None, "the tube's centre below the desk", 20),
        s(None, "the screws' size", 4, 0.6),
    ),
    "d-shaft-knob": (
        s(None, "the shaft's diameter", 6, 0.3),
        s(None, "the shaft's flat, 4.5 mm across from the far side", 4.5, 0.3),
        s(None, "how far it goes down the shaft: at least 8 mm, at most its 12", 10, 2),
    ),
    "wall-hook": (
        s(None, "the strap's width it makes room for: at least 40 mm", 50, 10),
        s(None, "the screws' size", 4, 0.6),
    ),
    "cable-comb": (
        s(None, "the number of slots", 6, 0),
        s(None, "the cables' diameter", 5, 0.6),
        s(None, "the cables' centre height", 10),
    ),
    "spool-holder": (
        s(None, "the spool's hole", 53, 3.5),
        s(None, "the spool's width the holder fits", 70, 5),
        s(None, "the screws' size", 4, 0.6),
    ),
    "pi5-nvme-case": (
        s(None, "the Pi's board, 85 mm long", 85),
        s(None, "the Pi's board, 56 mm wide", 56),
        s(None, "the mounting holes' spacing, 58 mm", 58),
        s(None, "the mounting holes' spacing, 49 mm", 49),
        s(None, "the standoffs between the boards", 12),
        s(None, "the NVMe Base Duo's length", 87.6),
        s(None, "the USB-C's height above the board", 3.2),
        s(None, "the micro HDMIs' height above the board", 3.4),
        s(None, "the tallest part on the Pi's top, bar the sockets", 4.4),
    ),
}


@dataclass
class Miss:
    """A stated value no size met, and the plan's sizes it was checked against."""

    what: str
    part: str | None
    value: float
    tol: float
    checked: list[dict[str, Any]]

    def said(self) -> str:
        if not self.checked:
            where = f"on {self.part}" if self.part else "in it"
            return f"the spec states {self.what}, {self.value:g}: your plan has no size {where}"
        values = sorted(
            {v for v in (_number(c.get("value")) for c in self.checked) if v is not None}
        )
        closest = min(values, key=lambda v: abs(v - self.value))
        return (
            f"the spec states {self.what}, {self.value:g}: "
            f"the nearest size your plan gives is {closest:g}"
        )


@dataclass
class Checked:
    """A plan's check: its shape's faults, the stated values it missed, and the plan."""

    wrong: list[str]
    misses: list[Miss]
    plan: dict[str, Any] | None

    @property
    def passed(self) -> bool:
        return not self.wrong and not self.misses

    def said(self) -> list[str]:
        return self.wrong + [m.said() for m in self.misses]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().removesuffix("mm").removesuffix("°").strip())
        except ValueError:
            return None
    return None


def read(text: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """The plan's JSON, or what's wrong with its shape. Names are recorded, not judged."""
    try:
        plan = json.loads(text) if isinstance(text, str) else text
    except json.JSONDecodeError as exc:
        return None, [f"the plan isn't JSON: {exc.msg} at character {exc.pos}"]
    if not isinstance(plan, dict):
        return None, ["the plan is a JSON object with parts, interfaces, sizes and fits"]
    wrong = [
        f"`{key}` is a list"
        for key in ("parts", "interfaces", "sizes", "fits")
        if not isinstance(plan.get(key), list)
    ]
    for size in plan.get("sizes") or []:
        if not isinstance(size, dict):
            wrong.append("each size is an object: `part`, `name`, `value`, `source`")
            break
        if _number(size.get("value")) is None:
            wrong.append(f"the size {json.dumps(size)[:80]} has no number for its value")
        if size.get("source") not in SOURCES:
            wrong.append(
                f"the size {json.dumps(size)[:80]}: `source` is one of {', '.join(SOURCES)}"
            )
    return (None, wrong) if wrong else (plan, [])


def on(stated_part: str | None, size: dict[str, Any]) -> bool:
    """Whether a size is on the stated value's part: any size, where the spec doesn't
    say which part (a one-part case, or a fit between parts)."""
    if stated_part is None:
        return True
    part = str(size.get("part") or "").lower().removesuffix(".step")
    return part == stated_part


def check(case: str, outputs: list[str], text: Any) -> Checked:
    """The plan against the case's files and the values its spec states, by value on
    the right part, whatever the size is called. Equal values on a part may share a size."""
    plan, wrong = read(text)
    if plan is None:
        return Checked(wrong, [], None)
    files = sorted(str(p.get("file")) for p in plan["parts"] if isinstance(p, dict))
    if files != sorted(outputs):
        given = ", ".join(files) or "none"
        wrong.append(f"the spec asks for {', '.join(outputs)}: your plan's files are {given}")
    misses = []
    for stated in STATED.get(case, ()):
        checked = [size for size in plan["sizes"] if on(stated.part, size)]
        values = [_number(size.get("value")) for size in checked]
        if not any(v is not None and abs(v - stated.value) <= stated.tol + 1e-9 for v in values):
            misses.append(Miss(stated.what, stated.part, stated.value, stated.tol, checked))
    return Checked(wrong, misses, plan)
