"""A dimensioned plan before code, checked against the model's own quotes.

mqucifer/model-performance#30, made generic for #40 (A1). In the base arm the model
sends `plan` before any `write`, `edit` or `run`: its parts and their files, the
interfaces between them, the key sizes with where each comes from, and how the parts
fit. Each size names its source:

- **`spec`:** it quotes the spec's words for it (`quote`). The quote must be in the
  spec's text, and the value must be one of the numbers in the quote.
- **`reference`:** it quotes the reference table it came from, which must be one the
  session can read (`skills/`).
- **`derived`** (worked out from other sizes) and **`chosen`** (the model's own
  decision): recorded, never judged.

So the check needs nothing of the case's. v1's per-case key of stated values is gone:
it judged unseen parts not at all, and it once told the model a value the spec doesn't
state (70 for a spool the spec says is 65 mm wide). A miss names the model's own entry
and quote, never a value the evaluation holds. Every check is kept in the run's
events, each miss with the entry it was checked against.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from cad_eval import skills

# After this many plans that miss, the gate opens anyway, so a run isn't spent on plans.
ATTEMPTS = 3
SOURCES = ("spec", "reference", "derived", "chosen")
QUOTED = ("spec", "reference")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def normal(text: str) -> str:
    """Text as a quote is compared: no markup, one space for any run of whitespace, and
    case folded, so a quote isn't judged on layout the model shouldn't have to copy."""
    text = re.sub(r"[*`_]", "", text).replace("−", "-").replace("×", "x")
    return re.sub(r"\s+", " ", text).strip().casefold()


# How a quote is matched to the spec: as `normal`, and a symbol however it's written,
# so "45 degree", "45 deg" and "45°", and "0.5 mm by 45" and "0.5 mm × 45", are one
# (V5 at 3706cd8: six of 31 calls went on the spelling of a degree). The audit keeps
# `normal`, which places a number by its position in the spec.
DEGREES = re.compile(r"(\d)\s*(?:°|degrees?\b|deg\b)")
TIMES = re.compile(r"(\d(?:\s*mm)?)\s*(?:x|by)\s*(?=-?\.?\d)")
UNIT = re.compile(r"\s*(?:mm|°|degrees?|deg)\s*$")


MM = re.compile(r"(\d)\s*mm\b")


def loose(text: str) -> str:
    text = MM.sub(r"\1 mm", normal(text))
    text = TIMES.sub(r"\1 x ", DEGREES.sub(r"\1 deg", text))
    return re.sub(r"\s+", " ", text).strip()


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        # A length in mm, or an angle in degrees however it's written.
        found = NUMBER.fullmatch(UNIT.sub("", value.strip().casefold()).strip())
        return float(found.group(0)) if found else None
    return None


@dataclass
class Miss:
    """A size whose quote doesn't hold, with the entry as the model wrote it."""

    entry: dict[str, Any]
    why: str  # not_in_spec, not_in_references, value_not_in_quote

    def said(self) -> str:
        name, value = self.entry.get("name"), self.entry.get("value")
        quote = str(self.entry.get("quote", ""))
        if self.why == "value_not_in_quote":
            return f'the size `{name}` ({value}) quotes "{quote}", which doesn\'t give {value}'
        where = "the spec" if self.why == "not_in_spec" else "the references you can read"
        return f'the size `{name}` quotes "{quote}", which isn\'t in {where}'


@dataclass
class Checked:
    """A plan's check: its shape's faults, its misses, and the plan as read."""

    wrong: list[str]
    misses: list[Miss]
    plan: dict[str, Any] | None

    @property
    def passed(self) -> bool:
        return not self.wrong and not self.misses

    def said(self) -> list[str]:
        return self.wrong + [m.said() for m in self.misses]


def read(text: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """The plan's JSON, or what's wrong with its shape. Names are recorded, not judged."""
    try:
        found = json.loads(text) if isinstance(text, str) else text
    except json.JSONDecodeError as exc:
        return None, [f"the plan isn't JSON: {exc.msg} at character {exc.pos}"]
    if not isinstance(found, dict):
        return None, ["the plan is a JSON object with parts, interfaces, sizes and fits"]
    wrong = [
        f"`{key}` is missing: send [] if there are none"
        if key not in found
        else f"`{key}` is a list (send [] if there are none)"
        for key in ("parts", "interfaces", "sizes", "fits")
        if not isinstance(found.get(key), list)
    ]
    for size in found.get("sizes") or []:
        if not isinstance(size, dict):
            wrong.append("each size is an object: `part`, `name`, `value`, `source`, `quote`")
            break
        shown = json.dumps(size)[:120]
        if number(size.get("value")) is None:
            wrong.append(
                f'the size {shown}: `value` is one number with its unit, such as 16 or "16 mm"; '
                "for a range or a placement, send a size for each number, or make it `chosen`"
            )
        if size.get("source") not in SOURCES:
            wrong.append(f"the size {shown}: `source` is one of {', '.join(SOURCES)}")
        elif size["source"] in QUOTED and not str(size.get("quote") or "").strip():
            wrong.append(f"the size {shown} comes from the {size['source']}: give its `quote`")
    return (None, wrong) if wrong else (found, [])


def references() -> str:
    """Every skill and reference file the session can read, as quotes are compared."""
    return loose("\n".join(p.read_text(encoding="utf-8") for p in skills.files(skills.SETS)))


def check(spec: str, outputs: list[str], text: Any) -> Checked:
    """The plan against the case's files and the model's own quotes."""
    found, wrong = read(text)
    if found is None:
        return Checked(wrong, [], None)
    files = sorted(str(p.get("file")) for p in found["parts"] if isinstance(p, dict))
    if files != sorted(outputs):
        given = ", ".join(files) or "none"
        wrong.append(f"the spec asks for {', '.join(outputs)}: your plan's files are {given}")
    in_spec, in_refs = loose(spec), None
    misses = []
    for size in found["sizes"]:
        if size["source"] not in QUOTED:
            continue
        quote = loose(str(size["quote"]))
        if size["source"] == "spec" and quote not in in_spec:
            misses.append(Miss(size, "not_in_spec"))
            continue
        if size["source"] == "reference":
            in_refs = references() if in_refs is None else in_refs
            if quote not in in_refs:
                misses.append(Miss(size, "not_in_references"))
                continue
        value = number(size["value"])
        # By magnitude: "3-4 mm" reads as 3 and -4, and its 4 is the spec's all the same.
        found_numbers = [abs(float(n)) for n in NUMBER.findall(quote)]
        if not any(abs(n - abs(value)) < 1e-9 for n in found_numbers):  # type: ignore[arg-type]
            misses.append(Miss(size, "value_not_in_quote"))
    return Checked(wrong, misses, found)
