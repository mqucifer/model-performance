"""The `view` tool (mqucifer/model-performance#29): the model's own files drawn in the
view image, with the case's keep-outs; the picture sent as the latest view only."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cad_eval import container, skills
from cad_eval.render import MARK
from cad_eval.session import SHOWN_BEFORE, Session
from cad_eval.tools import PartTools
from tests.cad_eval.fakes import FakeWorkspace, Ran

PNG = base64.b64encode(b"\x89PNG fake").decode()


class Drawn(FakeWorkspace):
    """A workspace whose render answers with a picture, or an error."""

    answer: dict[str, Any] = {"png": PNG, "view": "iso", "caption": ["base.step: colour 1"]}

    def exec(self, command: list[str], timeout: int = 0, stdin: str | None = None) -> Ran:
        if stdin and "CAD_EVAL_VIEW" in stdin:
            self.commands.append(command)
            return Ran("view", 0, MARK + json.dumps(self.answer))
        return super().exec(command, timeout, stdin)


def tools(tmp_path: Path, answer: dict | None = None) -> PartTools:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "base.step").write_text("step")
    workspace = Drawn(directory=tmp_path)
    if answer is not None:
        workspace.answer = answer
    return PartTools(tmp_path, workspace, arm="refs-measure-view", keepouts=["mate = 'board'"])


def test_a_view_draws_the_models_files_with_the_cases_keepouts(tmp_path: Path) -> None:
    t = tools(tmp_path)
    found = t.call("view", '{"files": "base.step", "view": "section x=40"}')
    assert found.outcome == "ok" and found.image == PNG
    request = json.loads(t.workspace.commands[-1][3])
    assert request == {
        "files": ["base.step"],
        "view": "section",
        "plane": {"axis": "x", "at": 40.0},
        "keepouts": ["mate = 'board'"],
    }


def test_a_view_it_cant_draw_fails_saying_why(tmp_path: Path) -> None:
    t = tools(tmp_path)
    assert t.call("view", '{"files": "base.step", "view": "sideways"}').why == "not_a_query"
    assert t.call("view", '{"files": "base.step", "view": "section q=1"}').why == "not_a_query"
    assert t.call("view", '{"files": "nothing.step", "view": "iso"}').why == "no_file"
    broken = tools(tmp_path / "b", {"error": "RuntimeError: no GL"})
    assert broken.call("view", '{"files": "base.step", "view": "iso"}').why == "unfinished"


def test_only_the_latest_picture_stays_in_the_conversation(tmp_path: Path) -> None:
    t = tools(tmp_path)
    session = Session("spec", t, lambda body: {}, "m", tmp_path / "events.jsonl")
    call = {
        "id": "c",
        "function": {"name": "view", "arguments": '{"files": "base.step", "view": "iso"}'},
    }
    session._tools([call])
    session._tools([call])
    pictures = [m for m in session.messages if isinstance(m.get("content"), list)]
    assert len(pictures) == 1
    assert pictures[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert any(m.get("content") == SHOWN_BEFORE for m in session.messages)
    assert session.views == 2 and (tmp_path / "views" / "2.png").exists()


def test_the_view_arm_runs_in_the_view_image_and_says_how_to_use_it() -> None:
    assert skills.image_for("refs-measure-view") == container.IMAGE_VIEW
    assert skills.image_for("refs-measure") == container.IMAGE
    assert skills.image_for(None) == container.IMAGE
    start = skills.start_for("refs-measure-view")
    assert skills.VIEW_LINE in start and skills.MEASURE_LINE in start
