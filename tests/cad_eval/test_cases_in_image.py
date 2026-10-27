"""Each harder case's checks, both ways, on real CadQuery in the evaluation's image.

Skipped where the image isn't built (CI): run them on the Mac after
`cad_eval/image/build.sh`. The threaded cases take minutes.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

import pytest

from cad_eval import audit, container
from cad_eval import run as cad
from cad_eval.cases import CASES
from cad_eval.tools import PartTools

HERE = Path(__file__).parent
pytestmark = pytest.mark.skipif(
    container.image_id() is None, reason=f"{container.IMAGE} isn't built"
)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("case")
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(directory, f"test-{directory.name}-{os.getpid()}")
        assert held.start().ok
        try:
            yield directory, held
        finally:
            held.stop()


def final(workspace: tuple[Path, object], script: Path, name: str) -> tuple[dict, list[dict]]:
    directory, held = workspace
    for left in directory.iterdir():
        if left.name != ".crew-home":
            left.unlink()
    shutil.copy(script, directory / "make.py")
    case = CASES[name]
    result = PartTools(directory, held, case.outputs()).final_case("make.py", cad.requests(case))
    assert result["code"] == 0, result["tail"]
    return cad.judge(case, result)


@pytest.mark.parametrize("name", list(CASES))
def test_the_reference_passes_every_check(workspace: tuple[Path, object], name: str) -> None:
    row, found = final(workspace, HERE / "reference" / f"{name}.py", name)
    assert [c["name"] for c in found if not c["ok"]] == []
    assert row["compiles"] and row["closed_mesh"] and row["within_tolerance"]
    # The audit lists exactly the checks that ran (`audit.py`, #40 V2).
    produced = sorted(f"{c['member']}/{c['name']}" for c in found)
    assert produced == sorted(c["check"] for c in audit.checks(CASES[name]))


@pytest.mark.parametrize("name", list(CASES))
def test_the_planted_wrong_one_fails_a_check(workspace: tuple[Path, object], name: str) -> None:
    row, _ = final(workspace, HERE / "wrong" / f"{name}.py", name)
    assert row["compiles"] and row["closed_mesh"]
    assert not row["within_tolerance"]
