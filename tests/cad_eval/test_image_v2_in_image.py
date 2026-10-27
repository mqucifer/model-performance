"""The v2 image (mqucifer/model-performance#40): the CadQuery image plus exactly one
pinned package, VTK rendering offscreen, and both indexes, read in the image itself
(skipped where it isn't built)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from cad_eval import container

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
)
BUILD = Path(container.__file__).parent / "image" / "build.sh"


def inside(image: str, *command: str) -> str:
    return subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image, *command],
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    ).stdout


def packages(image: str) -> set[str]:
    return set(inside(image, "dpkg-query", "-W", "-f=${Package}=${Version}\\n").split())


def test_it_is_the_pinned_cadquery_image_plus_one_pinned_package() -> None:
    added = packages(container.IMAGE_V2) - packages(container.IMAGE)
    removed = packages(container.IMAGE) - packages(container.IMAGE_V2)
    assert (added, removed) == ({"libosmesa6=22.3.6-1+deb12u2"}, set())
    pinned = re.search(r"BASE_ID=(sha256:\w+)", BUILD.read_text()).group(1)
    label = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.base.id"}}',
            container.IMAGE_V2,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert label == pinned


def test_the_python_packages_are_the_cadquery_images() -> None:
    freeze = ("python", "-m", "pip", "freeze", "--all")
    assert inside(container.IMAGE_V2, *freeze) == inside(container.IMAGE, *freeze)


def test_vtk_renders_offscreen() -> None:
    code = (
        "import vtk; w = vtk.vtkRenderWindow(); w.SetOffScreenRendering(1); "
        "r = vtk.vtkRenderer(); w.AddRenderer(r); w.Render(); print(w.GetClassName())"
    )
    assert inside(container.IMAGE_V2, "python", "-c", code).strip() == "vtkOSOpenGLRenderWindow"


def test_the_lookup_index_finds_inherited_members_and_all_of_ocp() -> None:
    index = json.loads(inside(container.IMAGE_V2, "cat", container.LOOKUP_INDEX))
    assert (index["cadquery"], index["ocp"]) == ("2.8.0", "7.9.3.1.1")
    by_name = {e["name"]: e for e in index["entries"]}
    fuse = by_name["cq.Shape.fuse"]
    assert {"cq.Solid", "cq.Face", "cq.Shape"} <= set(fuse["on"])
    assert "cq.Workplane" not in fuse["on"]
    # Compound defines its own fuse: its entry, apart.
    assert by_name["cq.Compound.fuse"]["on"] == ["cq.Compound"]
    assert "cq.func.fuse" in by_name
    assert "cq.Workplane.union" in by_name
    assert "OCP.BRepExtrema.BRepExtrema_DistShapeShape" in by_name
    assert len({n.split(".")[1] for n in by_name if n.startswith("OCP.")}) > 300


def test_the_docs_index_is_cadquerys_v2_8_0_under_its_licence() -> None:
    index = json.loads(inside(container.IMAGE_V2, "cat", container.DOCS_INDEX))
    assert index["source"] == {
        "repository": "https://github.com/CadQuery/cadquery",
        "tag": "v2.8.0",
        "commit": "fb4c6d41863aee270c46ab64397f0d2675e74be0",
        "licence": "Apache-2.0",
    }
    blocks = [b for c in index["chunks"] for b in c["blocks"]]
    assert len(index["chunks"]) > 200 and len(blocks) > 200
    # Every block was run at the build, and the ones calling show_object are flagged.
    assert all(isinstance(b["runs"], bool) for b in blocks)
    assert any(b["show_object"] for b in blocks)
    assert not any(b["runs"] for b in blocks if b["show_object"])


def hint(owner: str, name: str) -> dict:
    from cad_eval import hint as hint_module  # noqa: PLC0415

    done = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", container.IMAGE_V2]
        + ["python", "-I", "-", owner, name],
        input=Path(hint_module.__file__).read_text(),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    line = next(x for x in done.stdout.splitlines() if x.startswith(hint_module.MARK))
    return json.loads(line[len(hint_module.MARK) :])


def test_a_hint_names_where_a_real_name_is_and_what_is_near_a_made_up_one() -> None:
    """v1's commonest errors, answered from the installed library."""
    found = hint("Workplane", "isValid")
    assert found["on"][0] == "cq.Shape" and "cq.Solid" in found["on"]
    assert "cq.Workplane" not in found["on"]
    assert "cq.Shape" in hint("Workplane", "fuse")["on"]
    assert "makeFromWires" in hint("Face", "makeFace")["near"]


def search(tool: str, query: str, page: int = 1) -> dict:
    from cad_eval import search as search_module  # noqa: PLC0415

    done = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", container.IMAGE_V2]
        + ["python", "-I", "-", json.dumps({"tool": tool, "query": query, "page": page})],
        input=Path(search_module.__file__).read_text(),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    line = next(x for x in done.stdout.splitlines() if x.startswith(search_module.MARK))
    return json.loads(line[len(search_module.MARK) :])


def test_lookup_finds_what_v1s_missed() -> None:
    """v1's lookup said these didn't exist (the red-team review, rt_ocp.py)."""
    for query, owner in (
        ("Solid.fuse", "cq.Shape.fuse"),
        ("Solid.Volume", "cq.Shape.Volume"),
        ("Compound.BoundingBox", "cq.Shape.BoundingBox"),
    ):
        names = [f["name"] for f in search("lookup", query)["found"]]
        assert owner in names, (query, names)
    assert search("lookup", "func.fuse")["matches"] >= 1
    assert search("lookup", "BRepExtrema_DistShapeShape")["matches"] >= 1
    assert search("lookup", "Workplane.isValid")["matches"] == 0
    members = search("lookup", "OCP.BRepExtrema.BRepExtrema_DistShapeShape")["members"]
    assert any(m.startswith("Value(") for m in members)


def test_lookup_resolves_every_name_the_reference_solutions_call() -> None:
    """A coverage test: the references are a corpus to check lookup against, never a
    list for the model."""
    import ast  # noqa: PLC0415

    index = json.loads(inside(container.IMAGE_V2, "cat", container.LOOKUP_INDEX))
    members = {e["name"].rpartition(".")[2] for e in index["entries"]}
    used: set[str] = set()
    for script in (Path(__file__).parent / "reference").glob("*.py"):
        for node in ast.walk(ast.parse(script.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                used.add(node.func.attr)
    # Python's own (list.append, math.cos, str.format…) aren't CadQuery's.
    python = {"append", "extend", "format", "join", "items", "cos", "sin", "tan", "radians"}
    python |= {"sqrt", "atan2", "acos", "asin", "atan", "degrees", "hypot", "pi", "range", "floor"}
    python |= {"get", "keys", "values", "pop", "insert", "sort", "reverse", "copy", "update"}
    missing = sorted(used - members - python)
    assert missing == [], missing


def test_docs_finds_cadquerys_own_pages_and_says_what_wont_run_here() -> None:
    found = search("docs", "sweep helix thread")
    assert found["matches"] > 0
    assert any("elix" in f["title"] or "elix" in f["text"] for f in found["found"])
    notes = " ".join(f["note"] for p in (1, 2, 3) for f in search("docs", "box", p)["found"])
    assert "show_object" in notes


def test_the_lookup_index_rebuilds_byte_for_byte() -> None:
    """No memory address reaches it, so the image's index is what its builder makes
    again (the review of #41: three builds gave three hashes)."""
    from cad_eval.image import lookup_index  # noqa: PLC0415

    rebuilt = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", container.IMAGE_V2]
        + ["sh", "-c", "cd /tmp && python -I - /tmp/l.json >/dev/null && sha256sum /tmp/l.json"],
        input=Path(lookup_index.__file__).read_text(),
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    ).stdout.split()[0]
    baked = inside(container.IMAGE_V2, "sha256sum", container.LOOKUP_INDEX).split()[0]
    assert rebuilt == baked
