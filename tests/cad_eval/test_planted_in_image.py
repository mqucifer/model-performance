"""Planted wrong parts that the profile checks must fail (the review of #41): a thread
that isn't 60°, and gear teeth that aren't involutes. Each is a correct-looking part
right everywhere else, so the check that catches it is the one under test. In the v2
image the runs use (skipped where it isn't built)."""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

import pytest

from cad_eval import container
from cad_eval import run as cad
from cad_eval.cases import CASES
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
)
HERE = Path(__file__).parent / "planted"
# Each planted part, its case, and the checks that must fail it.
PLANTED = [
    ("m8-vee85.py", "m8-bolt", {"part/slope.flank_angle"}),
    ("m8-square.py", "m8-bolt", {"part/slope.flank_angle"}),
    # The second review of #41's: 55° two ways, and pitches either side of 1.25.
    ("m8-55-crest.py", "m8-bolt", {"part/slope.flank_angle"}),
    ("m8-55-halfpitch.py", "m8-bolt", {"part/slope.flank_angle"}),
    ("m8-pitch-1.15.py", "m8-bolt", {"part/period.flanks"}),
    ("m8-pitch-1.2.py", "m8-bolt", {"part/period.flanks"}),
    ("m8-pitch-1.3.py", "m8-bolt", {"part/period.flanks"}),
    ("spur-straight20.py", "spur-gear", {"part/share.involute_base", "part/share.involute_tip"}),
    (
        "gear-straight20.py",
        "gear-pair",
        {"gear-a/share.involute_base", "gear-b/share.involute_base"},
    ),
    (
        "gear-radial.py",
        "gear-pair",
        {"gear-a/share.involute_base", "gear-a/share.involute_tip"},
    ),
]


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("planted")
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        name = f"planted-{directory.name}-{os.getpid()}"
        held = container.held(directory, name, image=container.IMAGE_V2)
        assert held.start().ok
        try:
            yield directory, held
        finally:
            held.stop()


@pytest.mark.parametrize(("script", "name", "must_fail"), PLANTED)
def test_a_planted_wrong_profile_fails_its_check(
    workspace: tuple[Path, object], script: str, name: str, must_fail: set[str]
) -> None:
    directory, held = workspace
    for left in directory.iterdir():
        if left.name != ".crew-home":
            left.unlink()
    shutil.copy(HERE / script, directory / "make.py")
    case = CASES[name]
    result = PartTools(directory, held, case.outputs()).final_case("make.py", cad.requests(case))
    assert result["code"] == 0, result["tail"]
    row, found = cad.judge(case, result)
    failed = {f"{c['member']}/{c['name']}" for c in found if not c["ok"]}
    assert must_fail <= failed, (must_fail - failed, failed)
    assert row["compiles"] and not row["within_tolerance"]
