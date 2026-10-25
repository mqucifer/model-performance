"""Each part's checks, both ways, on real CadQuery in the evaluation's image.

They run in a container held by crew's own sandbox, as a session's do, and are
skipped where the image isn't built (CI): run them on the Mac after
`cad_eval/image/build.sh`.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

import pytest

from cad_eval import checks, container
from cad_eval.parts import PARTS
from cad_eval.tools import OUTPUT, PartTools

HERE = Path(__file__).parent
pytestmark = pytest.mark.skipif(
    container.image_id() is None, reason=f"{container.IMAGE} isn't built"
)


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("part")
    # crew's sandbox keeps its uv cache under the current directory: not the checkout.
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        workspace = container.held(directory, f"test-{directory.name}")
        assert workspace.start().ok
        try:
            yield PartTools(directory, workspace)
        finally:
            workspace.stop()


def final(tools: PartTools, script: Path, name: str) -> dict:
    for left in tools.directory.iterdir():
        if left.name != ".crew-home":
            left.unlink()
    shutil.copy(script, tools.directory / "part.py")
    part = PARTS[name]
    return tools.final("part.py", part.probes(), part.mate)


@pytest.mark.parametrize("name", list(PARTS))
def test_the_reference_part_passes_every_check(tools: PartTools, name: str) -> None:
    result = final(tools, HERE / "reference" / f"{name}.py", name)
    measured = result["measured"]
    assert result["code"] == 0, result["tail"]
    assert checks.valid(measured)
    assert checks.closed(measured)
    failing = [c for c in checks.dimensions(PARTS[name], measured) if not c.ok]
    assert failing == []


@pytest.mark.parametrize("name", list(PARTS))
def test_a_part_missing_a_feature_fails_a_check(tools: PartTools, name: str) -> None:
    result = final(tools, HERE / "wrong" / f"{name}.py", name)
    assert checks.valid(result["measured"])
    assert not all(c.ok for c in checks.dimensions(PARTS[name], result["measured"]))


def test_a_script_that_raises_doesnt_compile(tools: PartTools) -> None:
    result = final(tools, HERE / "wrong" / "raises.py", "spacer")
    assert result["code"] != 0
    assert not (tools.directory / OUTPUT).exists()
    assert not checks.valid(result["measured"])


def test_an_open_shell_isnt_a_closed_mesh(tools: PartTools) -> None:
    result = final(tools, HERE / "wrong" / "open-shell.py", "spacer")
    assert result["code"] == 0, result["tail"]
    assert not checks.closed(result["measured"])
    assert not checks.valid(result["measured"])


def test_inspect_measures_in_the_container_and_refuses_a_missing_file(tools: PartTools) -> None:
    final(tools, HERE / "reference" / "spacer.py", "spacer")
    seen = tools.call("inspect", '{"path": "part.step"}')
    assert seen.outcome == "ok"
    assert '"watertight": true' in seen.reply
    assert tools.call("inspect", '{"path": "nothing.step"}').outcome == "failed"
