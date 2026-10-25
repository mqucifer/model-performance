"""The skill arm's know-how: CadQuery, read on demand, in the crew's own shape.

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

ROOT = Path(__file__).parent / "skills" / "cadquery"


def files() -> list[Path]:
    return [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]


def front(path: Path) -> tuple[dict[str, str], str]:
    """A skill file's front matter, as `key: value` lines, and the text after it."""
    text = path.read_text(encoding="utf-8")
    _, head, body = text.split("---\n", 2)
    fields = dict(line.split(": ", 1) for line in head.strip().splitlines())
    return fields, body.lstrip()


def registry() -> dict[str, Any]:
    """Each skill file as crew's `Skill`, by its name."""
    from crew_org.session.skills import Skill  # noqa: PLC0415

    found = {}
    for path in files():
        fields, body = front(path)
        found[fields["name"]] = Skill(fields["name"], fields["description"], lambda b=body: b)
    return found


def start_line() -> str:
    """The one line the start adds in the skill arm, as crew's start names its skills."""
    from crew_org.session.skills import start_line as crew_start_line  # noqa: PLC0415

    return crew_start_line(list(registry().values())).replace("this Task", "this part")
