"""The skill arm (mqucifer/model-performance#21): its tools, its start line, the first
compile, and how many cases a run may run at once."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from cad_eval import run as cad
from cad_eval import skills
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace
from tests.cad_eval.test_cases import go
from tests.cad_eval.test_run import Run, answer, call


def tools(tmp_path: Path, arm: str | None) -> PartTools:
    return PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm=arm)


def test_the_skill_arm_offers_crews_skill_tool_and_lookup(tmp_path: Path) -> None:
    from crew_org.session.tools import SKILL_SPEC

    names = [s["function"]["name"] for s in tools(tmp_path, "skill").specs]
    assert names == ["write", "run", "inspect", "done", "blocked", "skill", "lookup"]
    assert tools(tmp_path, "skill").specs[5] == SKILL_SPEC
    # The baseline has neither: a call to one names no tool it has.
    baseline = tools(tmp_path, None)
    assert [s["function"]["name"] for s in baseline.specs][-1] == "blocked"
    assert baseline.call("skill", '{"name": "cadquery"}').outcome == "malformed"


def test_a_skill_is_read_by_name_and_an_unknown_one_fails(tmp_path: Path) -> None:
    t = tools(tmp_path, "skill")
    read = t.call("skill", '{"name": "cadquery-threads-helices"}')
    assert read.outcome == "ok" and "cq.Wire.makeHelix" in read.reply
    assert not read.reply.startswith("---")
    missing = t.call("skill", '{"name": "threads"}')
    assert (missing.outcome, missing.why) == ("failed", "unknown")
    assert "`cadquery-threads-helices`" in missing.reply


def test_lookup_runs_in_the_container_from_stdin(tmp_path: Path) -> None:
    t = tools(tmp_path, "skill")
    found = t.call("lookup", '{"query": "makeHelix"}')
    assert found.outcome == "ok"
    assert json.loads(found.reply)["found"][0]["name"] == "cq.Wire.makeHelix"
    command = t.workspace.commands[-1]
    assert command[:3] == ["python", "-I", "-"] and command[3] == "makeHelix"
    assert t.call("lookup", '{"query": "  "}').outcome == "failed"


def test_every_skill_file_has_a_name_and_a_line_and_skill_md_names_each_topic() -> None:
    found = skills.registry()
    assert set(found) == {
        "cadquery",
        "cadquery-sketch-extrude",
        "cadquery-selectors",
        "cadquery-threads-helices",
        "cadquery-assemblies-fits",
        "cadquery-errors",
    }
    guide = found["cadquery"].body()
    for name in found:
        if name != "cadquery":
            assert f"`{name}`" in guide
    for path in skills.files():
        text = path.read_text(encoding="utf-8")
        # Each file links the CadQuery pages it was distilled from.
        assert "https://cadquery.readthedocs.io/" in text, path.name
    line = skills.start_line()
    assert line.startswith("Skills for this part: `cadquery`,")
    assert "Read one with `skill` when you need it." in line


def test_the_arm_adds_its_start_line_and_records_itself(tmp_path: Path) -> None:
    r = Run(tmp_path, [answer(), answer(), answer()])
    row = go(r, "m8-bolt", arm="skill", concurrency=4)
    first = r.bodies[0]["messages"][1]["content"]
    assert first.endswith(skills.start_line())
    assert [t["function"]["name"] for t in r.bodies[0]["tools"]][-2:] == ["skill", "lookup"]
    assert (row["arm"], row["concurrency"]) == ("skill", 4)
    base = Run(tmp_path / "base", [answer(), answer(), answer()])
    row = go(base, "m8-bolt")
    assert base.bodies[0]["messages"][1]["content"] == cad.CASES["m8-bolt"].spec()
    assert (row["arm"], row["concurrency"]) == (None, 1)


def test_the_first_compile_is_the_call_after_which_a_run_wrote_every_output(
    tmp_path: Path,
) -> None:
    replies = [
        answer(call("write", {"path": "make.py", "content": "x"})),
        answer(call("run", {"path": "make.py"})),
        answer(call("run", {"path": "make.py"})),
        answer(call("done", {"script": "make.py"})),
    ]
    r = Run(tmp_path, replies, exits=[1, 0, 0])
    row = go(r, "m8-bolt")
    assert row["calls_to_first_compile"] == 3
    never = Run(tmp_path / "never", [answer(), answer(), answer()])
    assert go(never, "m8-bolt")["calls_to_first_compile"] is None


def fake_docker(total: int, used: list[str]) -> Any:
    def run(argv: list[str], **_: Any) -> Any:
        out = str(total) if argv[1] == "info" else "\n".join(f"{u} / 11GiB" for u in used)
        return type("Done", (), {"stdout": out})()

    return run


@pytest.mark.parametrize(
    ("total", "used", "room"),
    [
        (12 * 1024**3, ["1.162GiB", "211.5MiB", "51.32MiB"], 4),
        (12 * 1024**3, ["9GiB"], 1),
        (2 * 1024**3, ["100MiB"], 0),
    ],
)
def test_the_room_is_docker_free_memory_over_the_sandboxs_cap(
    total: int, used: list[str], room: int
) -> None:
    assert cad.sandbox_memory() == 2 * 1024**3
    assert cad.parallel_room(fake_docker(total, used)) == room


def test_docker_sizes_read_in_either_unit() -> None:
    assert cad.size("1.5GiB") == 1.5 * 1024**3
    assert cad.size("100kB") == 100_000
    assert cad.size("12MB") == 12_000_000
    assert cad.size("nonsense") == 0.0


def test_a_run_refuses_more_cases_at_once_than_memory_holds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cad, "parallel_room", lambda: 2)
    monkeypatch.setattr("swap.runners.ticks_running", lambda: False)
    monkeypatch.setattr(cad.container, "image_id", lambda: "sha256:abc")
    monkeypatch.setattr(cad, "builders_key", lambda _s: "k")

    class Lists:
        def __init__(self, *_: Any, **__: Any) -> None: ...
        def lists(self, _alias: str) -> bool:
            return True

        def close(self) -> None: ...

    monkeypatch.setattr(cad, "Sender", Lists)
    assert cad.main(["--hard", "--parallel", "3"]) == 2
    assert "Docker's free memory holds 2" in capsys.readouterr().err


def test_the_30_parts_dont_run_in_parallel() -> None:
    with pytest.raises(SystemExit):
        cad.main(["spacer", "--parallel", "2"])


def test_the_skill_mentions_only_names_written_as_the_api_has_them() -> None:
    # The two names the first run looked for and CadQuery doesn't have.
    text = "\n".join(p.read_text(encoding="utf-8") for p in skills.files())
    assert re.search(r"no `cq\.makeHelix`", text)


def ready(monkeypatch: pytest.MonkeyPatch, ticking: bool) -> list[Any]:
    """A run's preflight, faked: a tick running or not, and every case's evaluation caught."""
    monkeypatch.setattr("swap.runners.ticks_running", lambda: ticking)
    monkeypatch.setattr(cad, "parallel_room", lambda: 4)
    monkeypatch.setattr(cad.container, "image_id", lambda: "sha256:abc")
    monkeypatch.setattr(cad, "builders_key", lambda _s: "k")
    evaluated: list[Any] = []

    class Quiet:
        calls = 0

        def __init__(self, *_: Any, **__: Any) -> None: ...
        def lists(self, _alias: str) -> bool:
            return True

        def close(self) -> None: ...

    def evaluate(p: Any, *_: Any, **kw: Any) -> dict[str, Any]:
        evaluated.append((p.name, kw.get("arm"), kw.get("concurrency")))
        return {
            "ending": "done",
            "stop": None,
            "fault": None,
            "run": "r",
            **{
                k: None
                for k in (
                    "compiles",
                    "closed_mesh",
                    "within_tolerance",
                    "checks_passed",
                    "checks_total",
                    "calls",
                    "tool_calls",
                    "tool_reliability",
                    "malformed_tool_calls",
                    "ill_typed_tool_calls",
                    "failed_tool_calls",
                    "model_s",
                )
            },
        }

    monkeypatch.setattr(cad, "Sender", Quiet)
    monkeypatch.setattr(cad, "evaluate", evaluate)
    return evaluated


def test_harder_cases_run_alongside_a_tick_and_the_30_parts_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    evaluated = ready(monkeypatch, ticking=True)
    assert cad.main(["living-hinge", "m8-bolt", "--arm", "skill", "--parallel", "2"]) == 0
    assert sorted(evaluated) == [("living-hinge", "skill", 2), ("m8-bolt", "skill", 2)]
    assert "each row records it" in capsys.readouterr().err
    assert cad.main(["spacer"]) == 2
    assert "refused: a crew tick is running" in capsys.readouterr().err
