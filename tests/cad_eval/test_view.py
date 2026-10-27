"""The `view` tool (mqucifer/model-performance#29, in #40's base): only the model's own
files drawn, keep-outs included; only the latest picture in the conversation, each
replacement kept in the records so every request rebuilds."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cad_eval import render, transcript
from cad_eval.session import SHOWN_BEFORE, Session
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace, Ran
from tests.cad_eval.test_records import Scripted
from tests.cad_eval.test_run import answer, call

PNG = base64.b64encode(b"\x89PNG fake").decode()


class Drawn(FakeWorkspace):
    """A workspace whose render answers with a picture."""

    def exec(self, command: list[str], timeout: int = 0, stdin: str | None = None) -> Ran:
        if stdin and render.MARK.strip() in stdin:
            self.commands.append(command)
            found = {"png": PNG, "view": "iso", "caption": ["box.step: colour 1"], "painted": 0.3}
            return Ran("view", 0, render.MARK + json.dumps(found))
        return super().exec(command, timeout, stdin)


def tools(tmp_path: Path) -> PartTools:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("box.step", "board.step"):
        (tmp_path / name).write_text("step")
    t = PartTools(tmp_path, Drawn(directory=tmp_path), ["box.step"], arm="base")
    t.plan_passed = True
    return t


def test_a_view_draws_only_the_models_own_files(tmp_path: Path) -> None:
    t = tools(tmp_path)
    args = {"files": "box.step", "view": "section x=40", "keepouts": "board.step"}
    found = t.call("view", json.dumps(args))
    assert found.outcome == "ok" and found.image == PNG
    request = json.loads(t.workspace.commands[-1][3])
    assert request == {
        "files": ["box.step"],
        "view": "section",
        "plane": {"axis": "x", "at": 40.0},
        "keepouts": ["board.step"],
    }


def test_a_view_it_cant_draw_fails_saying_why(tmp_path: Path) -> None:
    t = tools(tmp_path)
    assert t.call("view", '{"files": "box.step", "view": "sideways"}').why == "not_a_query"
    assert t.call("view", '{"files": "box.step", "view": "section q=1"}').why == "not_a_query"
    assert t.call("view", '{"files": "nothing.step", "view": "iso"}').why == "no_file"
    assert t.call("view", '{"files": "box.step", "view": "iso", "keepouts": "x.step"}').why == (
        "no_file"
    )


def test_only_the_latest_picture_stays_and_each_request_rebuilds(tmp_path: Path) -> None:
    t = tools(tmp_path)
    look: dict[str, Any] = {"files": "box.step", "view": "iso"}
    send = Scripted(
        [
            answer(call("view", look, 1)),
            answer(call("view", look, 2)),
            answer(call("blocked", {"reason": "enough"}, 3)),
        ]
    )
    events = tmp_path / "events.jsonl"
    session = Session("spec", t, send, "m", events)
    session.run()
    last = send.bodies[-1]["messages"]
    pictures = [m for m in last if isinstance(m.get("content"), list)]
    assert len(pictures) == 1
    assert pictures[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert sum(m.get("content") == SHOWN_BEFORE for m in last) == 1
    assert session.views == 2 and (tmp_path / "views" / "2.png").exists()
    for n, sent in enumerate(send.bodies, start=1):
        assert transcript.rebuild(events, n) == sent
