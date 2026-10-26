"""The engineering references (mqucifer/model-performance#22): every value names its
source, the arms offer what they should, and the references agree with the cases."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cad_eval import skills
from cad_eval.cases import CASES
from cad_eval.tools import ARMS, PartTools
from tests.cad_eval.fakes import FakeWorkspace

REFERENCES = skills.files(("references",))
KEY = re.compile(r"\[([A-Z]+\d+)\]")


def tables(text: str) -> list[list[str]]:
    """Each markdown table's rows, header first, without its separator."""
    found: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("|"):
            if not set(line) <= set("|-: "):
                current.append(line)
        elif current:
            found.append(current)
            current = []
    if current:
        found.append(current)
    return found


@pytest.mark.parametrize("path", REFERENCES[1:], ids=lambda p: p.name)
def test_every_row_of_a_values_table_names_a_source_it_defines(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    defined = dict(re.findall(r"^- \[([A-Z]+\d+)\]: (https://\S+)", text, re.M))
    assert defined, path.name
    used: set[str] = set()
    for table in tables(text):
        header, rows = table[0], table[1:]
        assert "Source" in header, (path.name, header)
        for row in rows:
            source = row.rstrip(" |").rsplit("|", 1)[-1]
            keys = KEY.findall(source)
            assert keys, (path.name, row)
            assert set(keys) <= set(defined), (path.name, row)
            used |= set(KEY.findall(row))
    # Every source is used, by a row or by a note.
    assert set(defined) <= used | set(KEY.findall(text.split("## Sources")[0])), path.name


def test_the_fdm_reference_holds_no_printing_choices() -> None:
    # The Sponsor: printability (supports, orientation) is a second pass, not design.
    fdm = (skills.SKILLS / "references" / "references" / "fdm.md").read_text(encoding="utf-8")
    body = fdm.split("## Sources")[0].lower()
    assert "practice, not a standard" in body
    for word in ("overhang", "support material", "bridge", "infill", "layer height"):
        assert word not in body


def test_iso_273_agrees_with_the_cases_screw_hole_checks() -> None:
    """Both come from the standard: an M4 / 4 mm screw's clearance hole, fine to coarse,
    falls inside every case's hole radius."""
    text = (skills.SKILLS / "references" / "references" / "fasteners.md").read_text()
    m4 = re.search(r"\| M4 \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|", text)
    assert m4 is not None
    fine, medium, coarse = (float(v) / 2 for v in m4.groups())
    ranges = [h.radius for c in CASES.values() for m in c.members for h in m.holes]
    assert ranges
    for low, high in ranges:
        assert low <= fine <= medium <= coarse <= high


def tools(tmp_path: Path, arm: str) -> PartTools:
    return PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm=arm)


def test_each_arm_offers_its_own_skills_and_lookup_only_with_cadquery(tmp_path: Path) -> None:
    assert ARMS == ("skill", "refs", "skill-refs", "refs-measure", "refs-measure-view", "refs-plan")
    names = {arm: [s["function"]["name"] for s in tools(tmp_path, arm).specs][5:] for arm in ARMS}
    assert names == {
        "skill": ["skill", "lookup"],
        "refs": ["skill"],
        "skill-refs": ["skill", "lookup"],
        "refs-measure": ["skill", "measure"],
        "refs-measure-view": ["skill", "measure", "view"],
        "refs-plan": ["skill", "plan"],
    }
    refs = tools(tmp_path, "refs")
    assert refs.call("skill", '{"name": "ref-fasteners"}').outcome == "ok"
    assert refs.call("skill", '{"name": "cadquery"}').why == "unknown"
    assert refs.call("lookup", '{"query": "makeHelix"}').outcome == "malformed"
    both = tools(tmp_path, "skill-refs")
    assert both.call("skill", '{"name": "cadquery-threads-helices"}').outcome == "ok"
    assert both.call("skill", '{"name": "ref-fits"}').outcome == "ok"


def test_each_arms_start_line_names_its_own_skills() -> None:
    refs = skills.start_line(skills.for_arm("refs"))
    assert "`references`" in refs and "`ref-fasteners`" in refs and "`cadquery`" not in refs
    both = skills.start_line(skills.for_arm("skill-refs"))
    assert "`cadquery`" in both and "`ref-fdm`" in both
    assert skills.for_arm(None) == ()
