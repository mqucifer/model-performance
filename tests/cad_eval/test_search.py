"""`lookup` and `docs` over the v2 image's indexes (mqucifer/model-performance#40, A2):
names found through inheritance, each function once with every class it's on, paged;
the nearest names when nothing matches; and CadQuery's own 2.8.0 docs, searched."""

from __future__ import annotations

import json
from pathlib import Path

from cad_eval import search
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace

ENTRIES = [
    {"name": "cq.Shape", "kind": "class", "signature": "", "doc": "A shape."},
    {
        "name": "cq.Shape.fuse",
        "kind": "function",
        "signature": "(self, *toFuse, glue=False, tol=None)",
        "doc": "Fuse the positional arguments with this Shape.",
        "on": ["cq.Compound", "cq.Face", "cq.Shape", "cq.Solid"],
    },
    {
        "name": "cq.Compound.fuse",
        "kind": "function",
        "signature": "(self, *toFuse, glue=False, tol=None)",
        "doc": "Fuse shapes together.",
        "on": ["cq.Compound"],
    },
    {"name": "cq.func.fuse", "kind": "function", "signature": "(s1, s2, *shapes)", "doc": ""},
    {
        "name": "cq.Workplane.union",
        "kind": "function",
        "signature": "(self, toUnion=None, clean=True, glue=False, tol=None)",
        "doc": "Unions all of the items on the stack.",
        "on": ["cq.Workplane"],
    },
    {
        "name": "cq.Wire.makeHelix",
        "kind": "classmethod",
        "signature": "(pitch, height, radius)",
        "doc": "",
        "on": ["cq.Wire"],
    },
    {
        "name": "OCP.BRepExtrema.BRepExtrema_DistShapeShape",
        "kind": "class",
        "signature": "",
        "doc": "",
    },
]
CHUNKS = [
    {
        "source": "doc/sketch.rst",
        "title": "Sketch > Face-based API",
        "text": "Construct sketches from faces combined with boolean operations.",
        "blocks": [
            {"code": "s = cq.Sketch().trapezoid(4, 3, 90)", "show_object": True, "runs": False}
        ],
        "show_object": True,
    },
    {
        "source": "doc/examples.rst",
        "title": "Examples > Swept Helix",
        "text": "Sweep a profile along a helix made with Wire.makeHelix to make a thread.",
        "blocks": [{"code": "h = cq.Wire.makeHelix(1, 10, 5)", "show_object": False, "runs": True}],
        "show_object": False,
    },
]


def test_a_member_is_found_once_with_every_class_its_on() -> None:
    found = search.lookup(ENTRIES, "Solid.fuse")
    assert [f["name"] for f in found["found"]] == ["cq.Shape.fuse"]
    assert found["found"][0]["on"] == ["cq.Compound", "cq.Face", "cq.Shape", "cq.Solid"]


def test_a_fragment_finds_every_name_holding_it_exact_names_first() -> None:
    found = search.lookup(ENTRIES, "fuse")
    names = [f["name"] for f in found["found"]]
    assert set(names) == {"cq.Shape.fuse", "cq.Compound.fuse", "cq.func.fuse"}
    assert found["matches"] == 3


def test_results_are_paged() -> None:
    many = [
        {"name": f"cq.Thing.f{k:03}", "kind": "function", "signature": "", "doc": ""}
        for k in range(50)
    ]
    first = search.lookup(many, "Thing.f")
    assert (first["page"], first["pages"], len(first["found"])) == (1, 4, search.PAGE)
    last = search.lookup(many, "Thing.f", page=4)
    assert len(last["found"]) == 50 - 3 * search.PAGE


def test_no_match_gets_the_nearest_names() -> None:
    found = search.lookup(ENTRIES, "Wire.makeHelixx")
    assert found["matches"] == 0
    assert "cq.Wire.makeHelix" in found["near"]


def test_the_docs_search_ranks_by_the_querys_words_and_says_what_wont_run_here() -> None:
    found = search.docs(CHUNKS, "helix thread sweep")
    assert found["found"][0]["title"] == "Examples > Swept Helix"
    sketch = search.docs(CHUNKS, "sketch faces boolean")["found"][0]
    assert sketch["title"] == "Sketch > Face-based API"
    assert "show_object" in sketch["note"] and "didn't run" in sketch["note"]


def test_a_docs_query_with_no_match_says_so() -> None:
    assert search.docs(CHUNKS, "zzzz")["matches"] == 0


def tools(tmp_path: Path) -> PartTools:
    t = PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm="base")
    t.plan_passed = True
    return t


def test_the_base_arms_lookup_and_docs_run_the_search_in_the_container(tmp_path: Path) -> None:
    t = tools(tmp_path)
    found = t.call("lookup", json.dumps({"query": "Solid.fuse", "page": 2}))
    assert found.outcome == "ok"
    command = t.workspace.commands[-1]
    assert command[:3] == ["python", "-I", "-"]
    assert json.loads(command[3]) == {"tool": "lookup", "query": "Solid.fuse", "page": 2}
    found = t.call("docs", json.dumps({"query": "helix"}))
    assert found.outcome == "ok"
    assert json.loads(t.workspace.commands[-1][3]) == {"tool": "docs", "query": "helix", "page": 1}
    assert t.call("docs", json.dumps({"query": "  "})).why == "not_a_query"
    assert t.call("lookup", json.dumps({"query": "fuse", "page": 0})).why == "not_a_page"


def test_v1s_arms_keep_their_lookup(tmp_path: Path) -> None:
    v1 = PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm="skill")
    names = [s["function"]["name"] for s in v1.specs]
    assert "docs" not in names
    lookup = next(s for s in v1.specs if s["function"]["name"] == "lookup")
    assert list(lookup["function"]["parameters"]["properties"]) == ["query"]


def test_the_base_prompt_orients_the_model_and_names_one_way_to_check() -> None:
    from cad_eval.session import SYSTEM_CASE, system_for  # noqa: PLC0415

    base = system_for(["part.step"], base=True)
    assert "CadQuery 2.8.0" in base and "OCP 7.9.3" in base
    assert "two layers" in base and "Check a name before you use it" in base
    assert "`lookup`" in base and "`docs`" in base
    # One way to check a fit, and no inexact "only CadQuery" line.
    assert "only CadQuery" not in base
    assert base.count("`measure`") == 1
    # v1's prompt is as it ran.
    assert system_for(["part.step"]) == SYSTEM_CASE.format(
        saves="the part as STEP to `part.step` in the directory"
    )
