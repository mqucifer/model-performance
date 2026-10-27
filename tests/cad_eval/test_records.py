"""What a run keeps (mqucifer/model-performance#40, V4): every request, rebuilt exactly
from the records; each call's time and the model that served it; and the harness,
image, library, texts and serving a row ran on, read rather than typed."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from cad_eval import identity, transcript
from cad_eval import run as cad
from cad_eval.session import Session
from cad_eval.tools import PartTools
from common import results
from tests.cad_eval.fakes import FakeWorkspace
from tests.cad_eval.test_checks import measured
from tests.cad_eval.test_run import GOOD, Run, answer, call

SGLANG = """name: sglang
host: spark
runs_as: "container qwen3.8-27b-sglang, image lmsysorg/sglang:v0.5.22-cu130, pinned by \
digest sha256:e3a4f060…eae4a1ae, on the host network and IPC, privileged"
data:
  - "the model, RadixArk/Qwen3.8-27B-NVFP4-BF16-LMHead (its revision isn't pinned), and \
the draft, z-lab/Qwen3.8-27B-DFlash2 (pinned to revision 50307d4c…), in the weights cache"
"""


def test_every_request_is_rebuilt_exactly_from_the_records(tmp_path: Path) -> None:
    r = Run(tmp_path, GOOD, measured=measured("spacer"))
    row = r.go()
    events = r.records(row) / "events.jsonl"
    assert len(r.bodies) == 4
    for n, sent in enumerate(r.bodies, start=1):
        assert transcript.rebuild(events, n) == sent


class Scripted:
    """A `send` that answers from a list and keeps a copy of each body as it was sent."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = iter(replies)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(copy.deepcopy(body))
        return next(self.replies)


def test_a_rewritten_message_is_rebuilt_as_it_was_sent(tmp_path: Path) -> None:
    """The session may change an earlier message (a picture replaced by a note, or
    reasoning cleared): the records log each change, so each request rebuilds."""
    send = Scripted(
        [
            answer(call("write", {"path": "part.py", "content": "x = 1\n"})),
            answer(call("write", {"path": "part.py", "content": "x = 2\n"})),
            answer(call("blocked", {"reason": "enough"})),
        ]
    )
    tools = PartTools(tmp_path, FakeWorkspace(directory=tmp_path))
    session = Session("spec", tools, send, "m", tmp_path / "events.jsonl")
    original = session._call

    def call_then_rewrite() -> Any:
        found = original()
        if session.calls == 2:
            session.rewrite(1, "spec, as rewritten")
        return found

    session._call = call_then_rewrite  # type: ignore[method-assign]
    session.run()
    assert send.bodies[2]["messages"][1]["content"] == "spec, as rewritten"
    for n, sent in enumerate(send.bodies, start=1):
        assert transcript.rebuild(tmp_path / "events.jsonl", n) == sent


def test_each_call_records_its_time_and_the_model_that_served_it(tmp_path: Path) -> None:
    served = ["RadixArk/Qwen3.8-27B-NVFP4-BF16-LMHead", "RadixArk/Qwen3.8-27B-NVFP4-BF16-LMHead"]
    replies = [{**a, "model": m} for a, m in zip(GOOD[:2], served, strict=True)]
    replies += [{**a, "model": "other/model"} for a in GOOD[2:]]
    r = Run(tmp_path, replies, measured=measured("spacer"))
    row = r.go()
    events = [json.loads(line) for line in (r.records(row) / "events.jsonl").open()]
    calls = [e for e in events if e["kind"] == "call"]
    assert [c["served_model"] for c in calls] == [*served, "other/model", "other/model"]
    assert all(c["seconds"] >= 0 and c["at"].endswith("+00:00") for c in calls)
    # The row names the first served model, how many there were, and flags the change.
    assert row["served_model"] == served[0]
    assert (row["served_models"], row["served_changed"]) == (2, True)
    kept = json.loads((r.records(row) / "result.json").read_text())
    assert kept["served"] == [served[0], "other/model"]


def test_one_served_model_is_no_change(tmp_path: Path) -> None:
    replies = [{**a, "model": "RadixArk/Qwen3.8-27B"} for a in GOOD]
    row = Run(tmp_path, replies, measured=measured("spacer")).go()
    assert (row["served_models"], row["served_changed"]) == (1, False)


def test_the_serving_record_is_read_from_infras_inventory() -> None:
    found = identity.serving_from(SGLANG)
    assert found == {
        "serving_image": "lmsysorg/sglang:v0.5.22-cu130",
        "serving_digest": "sha256:e3a4f060...eae4a1ae",
        "serving_model": "RadixArk/Qwen3.8-27B-NVFP4-BF16-LMHead",
    }
    # A record that doesn't say is none, never a guess.
    assert identity.serving_from("name: sglang\n") == {
        "serving_image": None,
        "serving_digest": None,
        "serving_model": None,
    }


def test_the_row_names_the_harness_image_library_texts_and_serving(tmp_path: Path) -> None:
    record = {
        "serving_infra_commit": "1d0a29b",
        "serving_image": "lmsysorg/sglang:v0.5.22-cu130",
        "serving_digest": "sha256:e3a4f060...eae4a1ae",
        "serving_model": "RadixArk/Qwen3.8-27B-NVFP4-BF16-LMHead",
    }
    reads = iter([record, record])
    r = Run(tmp_path, GOOD, measured=measured("spacer"))
    row = r.go(serving_record=lambda: next(reads))
    assert len(row["harness_commit"]) == 40 and isinstance(row["harness_dirty"], bool)
    assert row["image_id"] == "sha256:abc"
    assert (row["cadquery_version"], row["ocp_version"]) == ("2.8.0", "7.9.3.1.1")
    assert len(row["skills_sha"]) == 64
    for key, value in record.items():
        assert row[key] == value
    assert row["serving"] == "lmsysorg/sglang:v0.5.22-cu130"
    assert row["serving_record_changed"] is False
    assert results.problems({"suite": "cad_eval", **row}) == []


def test_a_serving_record_that_changes_during_the_run_is_flagged(tmp_path: Path) -> None:
    before = {"serving_infra_commit": "1d0a29b", "serving_image": "lmsysorg/sglang:v0.5.22"}
    after = {"serving_infra_commit": "2e1b30c", "serving_image": "lmsysorg/sglang:v0.5.23"}
    reads = iter([before, after])
    row = Run(tmp_path, GOOD, measured=measured("spacer")).go(serving_record=lambda: next(reads))
    assert row["serving_image"] == "lmsysorg/sglang:v0.5.22"
    assert row["serving_record_changed"] is True


def test_a_harness_with_uncommitted_changes_refuses_to_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(identity, "harness", lambda: {"commit": "a" * 40, "dirty": True})
    assert cad.main(["spacer"]) == 2
    assert "uncommitted" in capsys.readouterr().err


@pytest.mark.real_harness
def test_the_harness_commit_is_this_checkout() -> None:
    found = identity.harness()
    assert len(found["commit"]) == 40 and isinstance(found["dirty"], bool)


def test_the_texts_hash_changes_with_any_skill_file(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("one")
    before = identity.texts_sha([tmp_path / "a.md"])
    (tmp_path / "a.md").write_text("two")
    assert identity.texts_sha([tmp_path / "a.md"]) != before


def test_a_failed_call_keeps_its_http_status(tmp_path: Path) -> None:
    r = Run(tmp_path, [httpx.Response(400, json={"error": "context too long"})])
    row = r.go()
    kept = json.loads((r.records(row) / "result.json").read_text())
    assert row["stop"] == "call_failed"
    assert kept["said"]["status"] == 400
