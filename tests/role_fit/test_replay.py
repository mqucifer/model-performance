"""Choosing, copying and replaying a case, against fakes: every ending leaves a row of numbers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from crew_org.calls import RUNAWAY_CHARS

from common import results, spend
from common.config import load
from role_fit import extract, run, select
from role_fit.cases import CASES, Case, UnknownCase, chosen
from role_fit.send import StreamingSender

CASE = Case(
    "0123456789abcdef0123456789abcdef",
    "settle",
    "product_owner",
    600,
    "Thing",
    2,
    False,
    False,
    "stop",
    100,
    50,
    40,
    12.5,
)
REQUEST = {
    "model": "crew-analysis",
    "messages": [{"role": "user", "content": "settle it"}],
    "max_tokens": 100,
    "response_format": {
        "type": "json_schema",
        "json_schema": {"name": "Thing", "schema": {"type": "object", "required": ["n"]}},
    },
    "metadata": {"user_api_key": "hashed"},
    "stream": True,
}


@pytest.fixture(autouse=True)
def proxy_log(monkeypatch: pytest.MonkeyPatch) -> list[set[str]]:
    """LiteLLM's log of other calls, faked: one other builder's call overlapped each run."""
    owns: list[set[str]] = []
    real = spend.others

    def others(since: Any, until: Any, own: Any, read: Any = None) -> Any:
        owns.append(set(own))
        return real(since, until, own, read=lambda _: "r1|x|crew-analysis\nr9|tick|crew-analysis\n")

    monkeypatch.setattr(spend, "others", others)
    return owns


def finished(at: str, call: str, response: str, **detail: Any) -> dict[str, Any]:
    base = {"call_id": call, "response_id": response, "repo": "mqucifer/sprint-metrics", "try": 1}
    return {"at": at, "kind": "llm.finished", "role": "Product Owner", "card": 600,
            "detail": {**base, **detail}}  # fmt: skip


def test_cases_are_chosen_one_per_card_with_refusals_first() -> None:
    found = [
        finished(
            "2026-10-12T00:00:00",
            "a",
            "1" * 32,
            output_schema="Settlement:x",
            attempt=1,
            prompt_tokens=10,
        ),  # fmt: skip
        finished(
            "2026-10-12T00:00:01",
            "b",
            "2" * 32,
            output_schema="Settlement:x",
            attempt=2,
            prompt_tokens=99,
        ),  # fmt: skip
        {
            "at": "2026-10-12T00:00:02",
            "kind": "llm.refused",
            "role": "Product Owner",
            "detail": {"call_id": "a", "empty": True},
        },  # fmt: skip
        finished("2026-10-12T00:00:03", "c", "3" * 32, output_schema="Settlement:x"),
        finished(
            "2026-10-12T00:00:04",
            "d",
            "4" * 32,
            output_schema="Settlement:x",
            repo="mqucifer/crew-presentation",
        ),  # fmt: skip
    ]
    found[3]["detail"]["try"] = 2
    calls = select.production(found)
    assert {c["id"][0] for c in calls} == {"1", "2"}  # first tries on sprint-metrics only
    settle = select.choose(calls)["settle"]
    # One card: the refused call is taken first, over the larger prompt.
    assert [c["id"][0] for c in settle] == ["1"]
    assert settle[0]["valid"] is False and settle[0]["empty"] is True


def test_the_kept_cases_cover_every_bucket_with_short_names_only() -> None:
    assert {c.bucket for c in CASES} == {b.name for b in select.BUCKETS}
    assert len({c.id for c in CASES}) == len(CASES)
    assert all(results.NAME.fullmatch(c.id) and results.NAME.fullmatch(c.role) for c in CASES)
    assert chosen(["judgement"]) == [c for c in CASES if c.group == "judgement"]
    with pytest.raises(UnknownCase):
        chosen(["no-such"])


def test_a_request_is_copied_once_without_litellms_own_keys(tmp_path: Path) -> None:
    settings = load(home=tmp_path)
    reads: list[str] = []

    def read(request_id: str) -> str:
        reads.append(request_id)
        return json.dumps({"request": REQUEST, "response": {"choices": []}})

    out = extract.extract(settings, CASE, read)
    kept = json.loads(out.read_text())
    assert "metadata" not in kept["request"] and "stream" not in kept["request"]
    assert kept["request"]["messages"] == REQUEST["messages"]
    assert out.stat().st_mode & 0o777 == 0o600
    extract.extract(settings, CASE, read)
    assert reads == [CASE.id]


def test_a_request_gone_from_the_log_is_reported_not_guessed(tmp_path: Path) -> None:
    settings = load(home=tmp_path)
    with pytest.raises(extract.NotFound):
        extract.extract(settings, CASE, lambda _: "")
    with pytest.raises(extract.NotFound):
        extract.extract(settings, CASE, lambda _: json.dumps({"request": {"model": "x"}}))
    with pytest.raises(ValueError):
        extract.query("1; drop table")


def stream_of(content: list[str], finish: str = "stop", thinking: str = "Wait. Hmm.") -> bytes:
    chunks = [{"id": "r1", "choices": [{"delta": {"reasoning_content": thinking}}]}]
    chunks += [{"id": "r1", "choices": [{"delta": {"content": piece}}]} for piece in content]
    chunks.append({"id": "r1", "choices": [{"delta": {}, "finish_reason": finish}]})
    usage = {"prompt_tokens": 100, "completion_tokens": 9}
    usage["completion_tokens_details"] = {"reasoning_tokens": 4}
    chunks.append({"id": "r1", "choices": [], "usage": usage})
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def sender(tmp_path: Path, seen: list[dict[str, Any]], body: bytes, status: int = 200, **kw):
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(status, content=body if status == 200 else b'{"echo": "prompt"}')

    kw.setdefault("tick", lambda: False)
    return StreamingSender(
        load(home=tmp_path), "sk-test", transport=httpx.MockTransport(answer), **kw
    )


def given(tmp_path: Path, production: dict[str, Any] | None = None):
    settings = load(home=tmp_path)
    response = production or {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    extract.extract(
        settings, CASE, lambda _: json.dumps({"request": REQUEST, "response": response})
    )
    return settings


def test_a_replay_sends_the_request_as_production_did_and_scores_both(
    tmp_path: Path, proxy_log: list[set[str]]
) -> None:
    settings = given(tmp_path)
    seen: list[dict[str, Any]] = []
    send = sender(tmp_path, seen, stream_of(['{"n": ', "1}"]))
    row = run.replay(CASE, settings, send, seed=2, results_dir=tmp_path / "results")
    assert seen[0]["messages"] == REQUEST["messages"] and seen[0]["seed"] == 2
    assert seen[0]["stream"] is True and "metadata" not in seen[0]
    assert row["ending"] == "done" and row["valid"] is True and row["calls"] == 1
    assert row["model_alias"] == "crew-analysis" and row["form"] == "json_schema"
    assert row["dated"] is True  # the pinned crew has no `Thing`
    assert row["reasoning_tokens"] == 4 and row["hedges_per_10k"] > 0
    assert row["prod_valid"] is False and row["prod_form_valid"] is False  # "{}" lacks `n`
    # The other calls on the proxy, but the replay's own (`r1`, its response id).
    assert proxy_log == [{"r1"}]
    assert (row["other_calls"], row["other_aliases"], row["arm"]) == (1, "tick", None)
    written = (tmp_path / "results" / "role_fit.jsonl").read_text().splitlines()
    assert results.problems(json.loads(written[0])) == []
    kept = settings.records_dir / "role_fit" / CASE.id / row["run"]
    assert json.loads((kept / "answer.json").read_text())["content"] == '{"n": 1}'


def test_a_candidate_alias_replaces_productions(tmp_path: Path) -> None:
    settings = given(tmp_path)
    seen: list[dict[str, Any]] = []
    send = sender(tmp_path, seen, stream_of(['{"n": 1}']), alias="crew-candidate")
    row = run.replay(CASE, settings, send, seed=1, results_dir=tmp_path / "results")
    assert seen[0]["model"] == "crew-candidate" and row["model_alias"] == "crew-candidate"


def test_a_runaway_is_cut_off_as_crew_cuts_it(tmp_path: Path) -> None:
    settings = given(tmp_path)
    body = stream_of(['{"n": 1', " " * (RUNAWAY_CHARS + 1), "never read"], finish="length")
    row = run.replay(CASE, settings, sender(tmp_path, [], body), seed=1,
                     results_dir=tmp_path / "results")  # fmt: skip
    assert row["finish_reason"] == "runaway" and row["runaway"] and row["why"] == "runaway"


def test_every_other_ending_leaves_a_row(tmp_path: Path) -> None:
    out = tmp_path / "results"
    settings = load(home=tmp_path)
    missing = run.replay(CASE, settings, sender(tmp_path, [], b""), seed=1, results_dir=out)
    assert (missing["ending"], missing["stop"], missing["calls"]) == ("refused", "no_request", 0)
    given(tmp_path)
    failed = run.replay(CASE, settings, sender(tmp_path, [], b"", status=500), seed=2,
                        results_dir=out)  # fmt: skip
    assert (failed["ending"], failed["stop"]) == ("interrupted", "call_failed")
    capped = run.replay(CASE, settings, sender(tmp_path, [], b"", cap=0), seed=3, results_dir=out)
    assert (capped["ending"], capped["stop"], capped["calls"]) == ("interrupted", "call_cap", 0)
    rows = [json.loads(line) for line in (out / "role_fit.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and all(results.problems(r) == [] for r in rows)
    # The failure's text names the status only: LiteLLM's body can echo the prompt.
    kept = json.loads((settings.records_dir / "role_fit" / CASE.id / failed["run"] /
                       "result.json").read_text())  # fmt: skip
    assert "prompt" not in kept["interrupted"]
