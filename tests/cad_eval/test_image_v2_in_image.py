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
