"""The sender calls only the proxy, with the key it's given, and stops at its cap."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from common.config import load
from common.litellm import CallCapReached, Sender

ANSWER = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


def sender(tmp_path: Path, seen: list[httpx.Request], status: int = 200, **kw) -> Sender:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=ANSWER if status == 200 else {"echo": "the prompt"})

    return Sender(load(home=tmp_path), "sk-test", transport=httpx.MockTransport(answer), **kw)


def test_a_call_goes_to_the_proxy_with_the_key(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    assert sender(tmp_path, seen)({"model": "crew-code-think", "messages": []}) == ANSWER
    assert str(seen[0].url) == "http://localhost:4000/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer sk-test"


def test_an_alias_replaces_the_roles_model(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    send = sender(tmp_path, seen, alias="crew-candidate")
    send({"model": "crew-code-think", "messages": []})
    assert json.loads(seen[0].content)["model"] == "crew-candidate"
    assert send.models == {"crew-candidate"}


def test_the_call_past_the_cap_is_refused_before_it_is_sent(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    send = sender(tmp_path, seen, cap=2)
    send({"model": "m"})
    send({"model": "m"})
    with pytest.raises(CallCapReached):
        send({"model": "m"})
    assert len(seen) == 2


def test_a_refusal_says_its_status_and_not_its_body(tmp_path: Path) -> None:
    with pytest.raises(httpx.HTTPStatusError) as raised:
        sender(tmp_path, [], status=400)({"model": "m"})
    assert "400" in str(raised.value)
    assert "prompt" not in str(raised.value)
