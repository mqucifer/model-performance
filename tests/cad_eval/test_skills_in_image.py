"""The CadQuery skill against the CadQuery the image runs, and `lookup` on it.

Like crew's skills, which are generated from what the crew runs so they can't drift,
every CadQuery name the skill mentions must exist in the installed library: a test in
the image, since the host has no CadQuery. Skipped where the image isn't built (CI).
"""

from __future__ import annotations

import contextlib
import json
import os
import re

import pytest

from cad_eval import container, skills
from cad_eval.tools import PartTools

pytestmark = pytest.mark.skipif(
    container.image_id() is None, reason=f"{container.IMAGE} isn't built"
)
# What a method the skill names in backticks, as `.name(`, may belong to.
OWNERS = ("Workplane", "Sketch", "Shape", "Solid", "Wire", "Edge", "Face", "Assembly")
RESOLVE = """
import json, sys
import cadquery as cq
owners = %r
missing = []
for name in json.loads(sys.argv[1]):
    if name.startswith("cq."):
        obj = cq
        try:
            for part in name.split(".")[1:]:
                obj = getattr(obj, part)
        except AttributeError:
            missing.append(name)
    elif not any(hasattr(getattr(cq, o), name) for o in owners):
        missing.append(name)
print("MISSING " + json.dumps(missing))
"""


def mentioned() -> list[str]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in skills.files())
    # Names the skill says CadQuery doesn't have aren't claimed to exist.
    text = re.sub(r"(?i)(there's no|not|no) `[^`]*`( or `[^`]*`)?", "", text)
    dotted = set(re.findall(r"\bcq\.[A-Za-z_][\w.]*[A-Za-z_]", text))
    methods = set(re.findall(r"`[^`]*?\.([a-z][A-Za-z0-9_]*)\(", text))
    return sorted(dotted | methods)


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("skill")
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(directory, f"test-{directory.name}-{os.getpid()}")
        assert held.start().ok
        try:
            yield PartTools(directory, held, arm="skill")
        finally:
            held.stop()


def test_every_cadquery_name_the_skill_mentions_exists_in_the_image(tools: PartTools) -> None:
    names = mentioned()
    assert "cq.Wire.makeHelix" in names and "extrude" in names
    done = tools.execute(["python", "-I", "-", json.dumps(names)], 120, stdin=RESOLVE % (OWNERS,))
    line = [x for x in done.output.splitlines() if x.startswith("MISSING ")][-1]
    assert json.loads(line[len("MISSING ") :]) == []


def test_lookup_finds_the_helix_the_first_run_missed(tools: PartTools) -> None:
    found = json.loads(tools.call("lookup", '{"query": "makeHelix"}').reply)
    assert found["found"][0]["name"] == "cq.Wire.makeHelix"
    assert "pitch" in found["found"][0]["signature"]
    assert "lefthand" in found["found"][0]["signature"]
    # No such function at the top level: nothing pretends there is.
    assert not any(f["name"] == "cq.makeHelix" for f in found["found"])


def test_lookup_lists_ocp_classes_and_refuses_nothing(tools: PartTools) -> None:
    found = json.loads(tools.call("lookup", '{"query": "OCP.BRepExtrema"}').reply)
    assert found["matches"] == 0 or found["found"][0]["name"].startswith("OCP.")
    topods = json.loads(tools.call("lookup", '{"query": "OCP.TopoDS.TopoDS_Shape"}').reply)
    assert topods["found"][0]["name"] == "OCP.TopoDS.TopoDS_Shape"
    none = json.loads(tools.call("lookup", '{"query": "noSuchThingAnywhere"}').reply)
    assert none["matches"] == 0


def examples() -> list[tuple[str, str]]:
    """Every fenced Python block in the skills, by its file."""
    found = []
    for path in skills.files(skills.SETS):
        for block in re.findall(r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.S):
            found.append((path.name, block))
    return found


def test_every_example_in_the_skill_runs_and_its_asserts_hold(tools: PartTools) -> None:
    """The meanings, not just the names (#40, A3): `|Z`, `>Z[n]`, a workplane's origin,
    `mirror`, which object has `isValid` and `fuse`, the thread recipe. Each is an
    example with its own asserts, run as written in the image."""
    found = examples()
    assert len(found) >= 7
    for k, (name, code) in enumerate(found):
        script = tools.directory / f"example_{k}.py"
        script.write_text(code)
        done = tools.execute(["python", script.name], 300)
        assert done.code == 0, f"{name}, example {k}:\n{done.output[-2000:]}"


def test_the_skill_links_the_docs_at_its_own_version() -> None:
    for path in skills.files(skills.SETS):
        text = path.read_text(encoding="utf-8")
        assert "/latest/" not in text and "readthedocs" not in text, path.name
        for link in re.findall(r"https://github\.com/CadQuery/cadquery/blob/([^/]+)/", text):
            assert link == "v2.8.0", path.name


def test_the_skill_holds_no_case_of_the_evaluation() -> None:
    """General, about how to approach a part: no case's name or its own numbers."""
    from cad_eval.cases import CASES  # noqa: PLC0415

    text = "\n".join(p.read_text(encoding="utf-8") for p in skills.files(("cadquery",)))
    for name in CASES:
        assert name not in text, name
    for word in ("gear", "involute", "Pi 5", "NVMe", "living hinge"):
        assert word.lower() not in text.lower(), word
