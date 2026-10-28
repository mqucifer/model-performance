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


def served(deployment: str) -> dict[str, Any]:
    """LiteLLM's headers as a response carries them: the deployment, never the key."""
    return {"x-litellm-model-id": deployment, "x-litellm-model-api-base": "http://spark/v1"}


def test_each_call_records_its_time_and_the_deployment_that_served_it(tmp_path: Path) -> None:
    """The alias (`model`) can't show a change; LiteLLM's deployment id can (the review
    of #41: every V5 call recorded `crew-code-think`)."""
    replies = [{**a, "model": "crew-code-think", "served": served("dep-a")} for a in GOOD[:2]]
    replies += [{**a, "model": "crew-code-think", "served": served("dep-b")} for a in GOOD[2:]]
    r = Run(tmp_path, replies, measured=measured("spacer"))
    row = r.go()
    events = [json.loads(line) for line in (r.records(row) / "events.jsonl").open()]
    calls = [e for e in events if e["kind"] == "call"]
    assert [c["served_model"] for c in calls] == ["dep-a", "dep-a", "dep-b", "dep-b"]
    # The address itself never in the records (the race review of #41): here the
    # record gave no port, so unverified.
    assert calls[0]["served"]["x-litellm-model-api-base"] == "unverified"
    assert "spark" not in json.dumps(calls)
    assert all(c["seconds"] >= 0 and c["at"].endswith("+00:00") for c in calls)
    assert row["served_model"] == "dep-a"
    assert (row["served_models"], row["served_changed"]) == (2, True)
    kept = json.loads((r.records(row) / "result.json").read_text())
    assert kept["served"] == ["dep-a", "dep-b"]


def test_one_deployment_is_no_change_and_the_alias_isnt_a_deployment(tmp_path: Path) -> None:
    replies = [{**a, "model": "crew-code-think", "served": served("dep-a")} for a in GOOD]
    row = Run(tmp_path, replies, measured=measured("spacer")).go()
    assert (row["served_model"], row["served_models"], row["served_changed"]) == ("dep-a", 1, False)
    bare = Run(tmp_path / "b", [{**a, "model": "crew-code-think"} for a in GOOD])
    bare.workspace.measured = measured("spacer")
    assert bare.go()["served_model"] is None


def test_litellms_headers_are_kept_but_never_the_keys_or_spend() -> None:
    from cad_eval.send import served_headers  # noqa: PLC0415

    headers = {
        "X-LiteLLM-Model-Id": "dep-a",
        "x-litellm-model-group": "crew-code-think",
        "x-litellm-key-spend": "0.1",
        "x-litellm-response-cost": "0",
        "content-type": "text/event-stream",
    }
    assert served_headers(headers) == {
        "x-litellm-model-id": "dep-a",
        "x-litellm-model-group": "crew-code-think",
    }


def test_the_serving_record_is_read_from_infras_inventory() -> None:
    found = identity.serving_from(SGLANG)
    assert found == {
        "serving_image": "lmsysorg/sglang:v0.5.22-cu130",
        "serving_digest": "sha256:e3a4f060...eae4a1ae",
        "serving_model": "RadixArk/Qwen3.8-27B-NVFP4-BF16-LMHead",
        "serving_port": None,
        "serving_reached_by": None,
    }
    # A record that doesn't say is none, never a guess.
    assert identity.serving_from("name: sglang\n") == {
        "serving_image": None,
        "serving_digest": None,
        "serving_model": None,
        "serving_port": None,
        "serving_reached_by": None,
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


def test_a_new_infra_commit_alone_isnt_a_change() -> None:
    same = {"serving_image": "lmsysorg/sglang:v0.5.22", "serving_route": "q"}
    assert not identity.changed(
        {**same, "serving_infra_commit": "a"}, {**same, "serving_infra_commit": "b"}
    )
    assert identity.changed(same, {**same, "serving_route": "other"})


CONFIG = """model_list:
  - model_name: crew-code
    litellm_params:
      model: openai/other
  - model_name: crew-code-think
    model_info:
      max_input_tokens: 262144
    litellm_params:
      model: openai/qwen3.8-27b-sglang
      api_base: os.environ/SGLANG_BASE_URL
"""


def test_the_serving_is_fetched_from_infras_main_with_the_aliases_route() -> None:
    import base64  # noqa: PLC0415

    asked: list[str] = []

    def fetch(path: str) -> str:
        asked.append(path)
        if path == "commits/main":
            return json.dumps({"sha": "1d0a29b" + "0" * 33})
        text = SGLANG if "sglang" in path else CONFIG
        return json.dumps({"content": base64.b64encode(text.encode()).decode()})

    found = identity.serving("crew-code-think", fetch)
    assert found["serving_infra_commit"] == "1d0a29b"
    assert found["serving_route"] == "qwen3.8-27b-sglang"
    assert found["serving_route_matches"] is True
    assert found["serving_image"] == "lmsysorg/sglang:v0.5.22-cu130"
    # Each file read at the commit it named, not whatever main is by then.
    assert all("ref=1d0a29b" in p for p in asked[1:])
    assert identity.route_from(CONFIG, "crew-code") == "other"


def test_a_serving_that_cant_be_fetched_is_none_not_a_local_guess() -> None:
    def down(_: str) -> str:
        raise OSError("no network")

    found = identity.serving("crew-code-think", down)
    assert found["serving_infra_commit"] is None and found["serving_route"] is None


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


def test_each_calls_serving_is_compared_with_infras_record() -> None:
    """What's readable in LiteLLM's headers, against infra's record (the second review
    of #41): the model group is the alias asked for, and the api base reaches SGLang at
    the host and port infra records. What can't be compared is never a match (the final
    review: a failed fetch, one header alone, read as verified)."""
    record = {"serving_port": "8888"}
    good = {
        "x-litellm-model-group": "crew-code-think",
        "x-litellm-model-api-base": "http://a:8888/v1",
    }
    alias = "crew-code-think"
    assert identity.mismatch(good, alias, record, "a") == []
    assert identity.mismatch(good, alias, record, "A") == []
    wrong_group = {**good, "x-litellm-model-group": "crew-candidate"}
    assert identity.mismatch(wrong_group, alias, record, "a") == ["model_group"]
    wrong_port = {**good, "x-litellm-model-api-base": "http://a:9999/v1"}
    assert identity.mismatch(wrong_port, alias, record, "a") == ["api_port"]
    wrong_host = {**good, "x-litellm-model-api-base": "http://b:8888/v1"}

    def resolve(name: str) -> frozenset[str]:
        # As getaddrinfo: a name to its address, an address to itself.
        known = {"a": "addr-one", "b": "addr-two"}
        if name in known.values():
            return frozenset({name})
        return frozenset({known[name]}) if name in known else frozenset()

    assert identity.mismatch(wrong_host, alias, record, "a", resolve) == ["api_host"]
    # One host by its address, the other by its name: the same, so a match.
    by_address = {**good, "x-litellm-model-api-base": "http://addr-one:8888/v1"}
    assert identity.mismatch(by_address, alias, record, "a", resolve) == []
    nowhere = {**good, "x-litellm-model-api-base": "http://c:8888/v1"}
    assert identity.mismatch(nowhere, alias, record, "a", resolve) == ["unresolved_host"]
    assert identity.mismatch({}, alias, record, "a") == ["unverified"]
    # One header alone, and a record with no port or host, say they can't compare.
    only_group = {"x-litellm-model-group": alias}
    assert identity.mismatch(only_group, alias, record, "a") == ["no_api_base"]
    only_base = {"x-litellm-model-api-base": "http://a:8888/v1"}
    assert identity.mismatch(only_base, alias, record, "a") == ["no_model_group"]
    assert identity.mismatch(good, alias, {}, "a") == ["no_record_port"]
    assert identity.mismatch(good, alias, record, None) == ["no_record_host"]
    for found in (["no_api_base"], ["no_record_port"], ["no_record_host"], ["unverified"]):
        assert set(found) <= set(identity.UNVERIFIED) and not set(found) & set(identity.MISMATCHES)
    assert (
        identity.serving_from(SGLANG + "ports:\n  api: 8888, on every interface\n")["serving_port"]
        == "8888"
    )


def test_the_host_is_read_by_the_name_infra_records_never_kept(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts.env"
    hosts.write_text("SPARK_ADDR=a.example\n")
    assert identity.serving_from("reached_by: SPARK_ADDR   # note\n")["serving_reached_by"] == (
        "SPARK_ADDR"
    )
    record = {"serving_reached_by": "SPARK_ADDR"}

    def nowhere(name: str) -> frozenset[str]:
        return frozenset()

    def known(name: str) -> frozenset[str]:
        return frozenset({"addr-one"})

    def ssh(name: str) -> str | None:
        return "alias-target.example" if name == "a.example" else None

    # A name DNS knows is the host; an SSH alias it doesn't is the host its config names.
    assert identity.reached_host(record, hosts, resolve=known, alias=ssh) == "a.example"
    assert identity.reached_host(record, hosts, resolve=nowhere, alias=ssh) == "alias-target.example"
    hosts.write_text("SPARK_ADDR=other\n")
    assert identity.reached_host(record, hosts, resolve=nowhere, alias=ssh) == "other"
    hosts.write_text("SPARK_ADDR=a.example\n")
    assert identity.reached_host({}, hosts) is None
    assert identity.reached_host(record, tmp_path / "none.env") is None
    assert (
        identity.ssh_hostname(
            "spark",
            run=lambda *a, **k: type("R", (), {"stdout": "user q\nhostname alias-target.example\n"})(),
        )
        == "alias-target.example"
    )
    assert (
        identity.ssh_hostname("x", run=lambda *a, **k: type("R", (), {"stdout": "hostname x\n"})())
        is None
    )


def test_a_failed_fetch_reads_unverified_on_the_row(tmp_path: Path) -> None:
    replies = [
        {
            **a,
            "served": {
                "x-litellm-model-id": "d",
                "x-litellm-model-group": "crew-code-think",
                "x-litellm-model-api-base": "http://a:8888/v1",
            },
        }
        for a in GOOD
    ]
    r = Run(tmp_path, replies, measured=measured("spacer"))
    row = r.go(
        serving_record=lambda: identity.serving(fetch=lambda path: (_ for _ in ()).throw(OSError()))
    )
    assert row["served_unverified"] is True and row["served_mismatch"] is False


def test_the_row_flags_a_served_mismatch(tmp_path: Path) -> None:
    replies = [
        {
            **a,
            "served": {
                "x-litellm-model-id": "d",
                "x-litellm-model-group": "crew-candidate",
                "x-litellm-model-api-base": "http://a:8888/v1",
            },
        }
        for a in GOOD
    ]
    r = Run(tmp_path, replies, measured=measured("spacer"))
    row = r.go(serving_record=lambda: {"serving_port": "8888"})
    assert row["served_mismatch"] is True and row["served_unverified"] is False
    events = [json.loads(x) for x in (r.records(row) / "events.jsonl").open()]
    assert [e["served_mismatch"] for e in events if e["kind"] == "call"][0] == ["model_group"]


def test_a_calls_event_never_holds_the_api_bases_address() -> None:
    headers = {"x-litellm-model-id": "d", "x-litellm-model-api-base": "http://a:8888/v1"}
    assert identity.logged(headers, []) == {
        "x-litellm-model-id": "d",
        "x-litellm-model-api-base": "matched",
    }
    assert identity.logged(headers, ["api_host"])["x-litellm-model-api-base"] == "mismatched"
    assert identity.logged(headers, ["no_record_host"])["x-litellm-model-api-base"] == "unverified"


def test_a_run_with_no_calls_reads_unverified(tmp_path: Path) -> None:
    r = Run(tmp_path, [], measured=measured("spacer"))
    row = r.go()
    assert row["served_unverified"] is True
