"""The docs index's builder (mqucifer/model-performance#40, A2): CadQuery's own 2.8.0
documentation and examples, cut into sections, each with its code, and each example
that calls CQ-editor's `show_object` flagged, since the sandbox has no such thing."""

from __future__ import annotations

from pathlib import Path

from cad_eval.image import docs_index

RST = """\
.. _sketchtutorial:

******
Sketch
******

Sketch tutorial
---------------

The purpose of this section is to demonstrate :py:meth:`Sketch.trapezoid` and **modes**.

Face-based API
==============

The main approach.

.. cadquery::
    :height: 600px

    import cadquery as cq

    result = cq.Sketch().trapezoid(4, 3, 90)

    show_object(result)

Then a plain literal block::

    r = cq.Workplane().box(1, 1, 1)

And some code:

.. code-block:: python

    s = cq.Sketch().circle(1)
"""

EXAMPLE = """import cadquery as cq

# A simple block
result = cq.Workplane("XY").box(80, 60, 10)

show_object(result)
"""


def source(tmp_path: Path) -> Path:
    (tmp_path / "doc").mkdir()
    (tmp_path / "examples").mkdir()
    (tmp_path / "doc" / "sketch.rst").write_text(RST)
    (tmp_path / "doc" / "conf.py").write_text("project = 'x'\n")
    (tmp_path / "examples" / "Ex001_Simple_Block.py").write_text(EXAMPLE)
    return tmp_path


def test_sections_carry_their_heading_path_text_and_code(tmp_path: Path) -> None:
    chunks = docs_index.chunks(source(tmp_path))
    titles = [c["title"] for c in chunks]
    assert "Sketch > Sketch tutorial > Face-based API" in titles
    face = next(c for c in chunks if c["title"].endswith("Face-based API"))
    assert face["source"] == "doc/sketch.rst"
    assert [b["code"] for b in face["blocks"]] == [
        "import cadquery as cq\n\nresult = cq.Sketch().trapezoid(4, 3, 90)\n\nshow_object(result)",
        "r = cq.Workplane().box(1, 1, 1)",
        "s = cq.Sketch().circle(1)",
    ]
    # A directive's options aren't code.
    assert ":height:" not in face["text"]


def test_show_object_is_flagged_on_its_block_and_section(tmp_path: Path) -> None:
    chunks = docs_index.chunks(source(tmp_path))
    face = next(c for c in chunks if c["title"].endswith("Face-based API"))
    assert [b["show_object"] for b in face["blocks"]] == [True, False, False]
    assert face["show_object"] is True
    tutorial = next(c for c in chunks if c["title"] == "Sketch > Sketch tutorial")
    assert tutorial["show_object"] is False


def test_markup_is_read_as_plain_text(tmp_path: Path) -> None:
    chunks = docs_index.chunks(source(tmp_path))
    tutorial = next(c for c in chunks if c["title"] == "Sketch > Sketch tutorial")
    assert "demonstrate Sketch.trapezoid and modes." in tutorial["text"]


def test_each_example_is_one_chunk_named_by_its_file(tmp_path: Path) -> None:
    chunks = docs_index.chunks(source(tmp_path))
    example = next(c for c in chunks if c["source"] == "examples/Ex001_Simple_Block.py")
    assert example["title"] == "Example: Simple Block"
    assert example["blocks"] == [{"code": EXAMPLE.strip(), "show_object": True, "runs": None}]


def test_only_the_docs_text_and_examples_are_read(tmp_path: Path) -> None:
    sources = {c["source"] for c in docs_index.chunks(source(tmp_path))}
    assert sources == {"doc/sketch.rst", "examples/Ex001_Simple_Block.py"}


def test_a_long_section_is_cut_without_cutting_a_block(tmp_path: Path) -> None:
    long = "Words. " * 600
    rst = f"Title\n=====\n\n{long}\n\n.. code-block:: python\n\n    x = 1\n\n{long}\n"
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "long.rst").write_text(rst)
    pieces = docs_index.chunks(tmp_path)
    assert len(pieces) > 1
    assert all(len(p["text"]) <= docs_index.CHUNK_CHARS + 200 for p in pieces)
    assert sum(len(p["blocks"]) for p in pieces) == 1


def test_the_index_names_its_source_and_licence(tmp_path: Path) -> None:
    root = source(tmp_path)
    (root / "LICENSE").write_text(
        "CadQuery\n\nunder the terms of the Apache Public License, v 2.0\n\n Apache License\n"
    )
    index = docs_index.build(root, commit="fb4c6d4", tag="v2.8.0")
    assert index["source"] == {
        "repository": "https://github.com/CadQuery/cadquery",
        "tag": "v2.8.0",
        "commit": "fb4c6d4",
        "licence": "Apache-2.0",
    }
    assert index["chunks"] == docs_index.chunks(root)


def test_a_source_without_its_licence_is_refused(tmp_path: Path) -> None:
    root = source(tmp_path)
    (root / "LICENSE").write_text("All rights reserved.\n")
    try:
        docs_index.build(root, commit="x", tag="v2.8.0")
    except docs_index.NotLicensed:
        return
    raise AssertionError("an unlicensed source was indexed")
