"""The arms' know-how: CadQuery, and engineering values, read on demand, in the crew's shape.

mqucifer/model-performance#21. The crew offers a session a skill by name, in one line
of its start, and the session reads it with a `skill` tool (crew's `session/skills.py`,
crew#839). This is that mechanism, reused: crew's `Skill` and `start_line`, and a tool
with crew's own `skill` spec. What isn't crew's is where the skills are registered.
Crew's `SKILLS` holds only its own, so the CAD skills are registered here: a later
crew change could let it take skills from outside.

The text is the Agent Skills layout, `skills/cadquery/SKILL.md` and its
`references/*.md`, each a skill of its own, so a topic is read only when it's needed.
Each file's front matter gives its name and the one-line description the start names.
It's distilled from CadQuery's documentation for the version the image pins, 2.8.0,
each section linking its page, and a test in the image checks every CadQuery name it
mentions exists there (`tests/cad_eval/test_skills_in_image.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SKILLS = Path(__file__).parent / "skills"
# Each set of skills, by its directory under `skills/`: a `SKILL.md` and its
# `references/*.md`. `cadquery` is #21's; `references`, the engineering values, is
# mqucifer/model-performance#22's.
SETS = ("cadquery", "references")
# What each arm offers: its sets, whether it has `lookup` (CadQuery's names), and its
# other tools (`measure`, mqucifer/model-performance#28).
ARMS: dict[str, tuple[tuple[str, ...], bool, tuple[str, ...]]] = {
    "skill": (("cadquery",), True, ()),
    "refs": (("references",), False, ()),
    "skill-refs": (("cadquery", "references"), True, ()),
    "refs-measure": (("references",), False, ("measure",)),
    "refs-measure-view": (("references",), False, ("measure", "view")),
}
# What the start adds where an arm has `measure`: check the part against the values the
# spec states, never the evaluation's own checks, which the model never sees.
MEASURE_LINE = (
    "Before `done`, measure what the spec states (each hole, gap, clearance and "
    "position it names) on your part with `measure`, and compare."
)


def files(sets: tuple[str, ...] = ("cadquery",)) -> list[Path]:
    found = []
    for name in sets:
        root = SKILLS / name
        found += [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]
    return found


def front(path: Path) -> tuple[dict[str, str], str]:
    """A skill file's front matter, as `key: value` lines, and the text after it."""
    text = path.read_text(encoding="utf-8")
    _, head, body = text.split("---\n", 2)
    fields = dict(line.split(": ", 1) for line in head.strip().splitlines())
    return fields, body.lstrip()


def registry(sets: tuple[str, ...] = ("cadquery",)) -> dict[str, Any]:
    """Each skill file of `sets` as crew's `Skill`, by its name."""
    from crew_org.session.skills import Skill  # noqa: PLC0415

    found = {}
    for path in files(sets):
        fields, body = front(path)
        found[fields["name"]] = Skill(fields["name"], fields["description"], lambda b=body: b)
    return found


def for_arm(arm: str | None) -> tuple[str, ...]:
    """The skill sets an arm offers: none for the baseline."""
    return ARMS[arm][0] if arm else ()


# What the start adds where an arm has `view` (mqucifer/model-performance#29).
VIEW_LINE = (
    "Look at your parts with `view`: top, front, side, iso, a section, or exploded, with "
    "the spec's keep-outs drawn in. The picture is to notice a fault; `measure` sizes it."
)


def image_for(arm: str | None) -> str:
    """The container image an arm runs in: the view image where it has `view`."""
    from cad_eval import container  # noqa: PLC0415

    return container.IMAGE_VIEW if arm and "view" in ARMS[arm][2] else container.IMAGE


def start_for(arm: str | None) -> str:
    """The start's added lines for an arm: its skills, and `measure`'s if it has it."""
    if not arm:
        return ""
    sets, _, tools = ARMS[arm]
    lines = [start_line(sets)] if sets else []
    if "measure" in tools:
        lines.append(MEASURE_LINE)
    if "view" in tools:
        lines.append(VIEW_LINE)
    return "\n".join(lines)


def start_line(sets: tuple[str, ...] = ("cadquery",)) -> str:
    """The one line the start adds in an arm, as crew's start names its skills."""
    from crew_org.session.skills import start_line as crew_start_line  # noqa: PLC0415

    return crew_start_line(list(registry(sets).values())).replace("this Task", "this part")
