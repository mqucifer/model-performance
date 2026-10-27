"""The `measure` tool (mqucifer/model-performance#28, in #40's base): the model's own
part and query, nothing of the case's, judged as every tool call is."""

from __future__ import annotations

import json
from pathlib import Path

from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace


def tools(tmp_path: Path, measured: dict | None = None) -> PartTools:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "part.step").write_text("step")
    return PartTools(
        tmp_path, FakeWorkspace(directory=tmp_path, measured=measured or {}), arm="base"
    )


def test_the_measure_request_carries_only_the_path_and_the_query(tmp_path: Path) -> None:
    t = tools(tmp_path, {"hole": {"diameter": 4.5}})
    found = t.call("measure", '{"path": "part.step", "query": "hole 0,0,5"}')
    assert found.outcome == "ok" and json.loads(found.reply)["hole"]["diameter"] == 4.5
    request = json.loads(t.workspace.commands[-1][3])
    # The guard against teaching to the test: no probes, bounds, volumes or mates.
    assert request == {"path": "part.step", "query": "hole 0,0,5"}


def test_a_bad_query_or_file_fails_and_an_empty_answer_is_still_the_tools_doing(
    tmp_path: Path,
) -> None:
    usage = tools(tmp_path, {"error": "query: one of `hole x,y,z`, ..."})
    assert usage.call("measure", '{"path": "part.step", "query": "spin"}').why == "not_a_query"
    t = tools(tmp_path / "b")
    assert t.call("measure", '{"path": "nothing.step", "query": "position >Z"}').why == "no_file"
    assert t.call("measure", '{"path": "part.step", "query": "  "}').why == "not_a_query"
    none = tools(tmp_path / "c", {"error": "no faces for >Q"})
    assert none.call("measure", '{"path": "part.step", "query": "position >Q"}').outcome == "ok"
    broken = tools(tmp_path / "d", {"error": "the measure didn't finish (exit 137)"})
    assert (
        broken.call("measure", '{"path": "part.step", "query": "position >Z"}').why == "unfinished"
    )


def test_the_base_has_it_and_v1s_arms_dont(tmp_path: Path) -> None:
    refs = PartTools(tmp_path, FakeWorkspace(directory=tmp_path), arm="refs")
    assert (
        refs.call("measure", '{"path": "part.step", "query": "position >Z"}').outcome == "malformed"
    )
    assert "measure" in [s["function"]["name"] for s in tools(tmp_path / "b").specs]
