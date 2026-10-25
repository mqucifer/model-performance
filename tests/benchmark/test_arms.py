"""The arms, apart from a run: what each sends, and when an answer refuses it."""

from __future__ import annotations

from typing import Any

import pytest

from benchmark.arms import BUDGET_SLACK, ArmNotInEffect, UnknownArm, arm, reasoning_tokens


def echo(seen: list[dict[str, Any]], reasoning: int = 0) -> Any:
    def send(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body)
        return {"usage": {"reasoning_tokens": reasoning}}

    return send


def test_sized_arms_read_their_size() -> None:
    assert arm("compact-50").compact_at == 50_000
    budget = arm("budget-128")
    assert budget.body == {"custom_params": {"thinking_budget": 128}}
    assert budget.max_reasoning == 128 + BUDGET_SLACK


@pytest.mark.parametrize("name", ["warp-9", "budget-0", "compact-", "budget-1.5", "think-off "])
def test_an_unknown_arm_is_refused(name: str) -> None:
    with pytest.raises(UnknownArm):
        arm(name)


def test_effort_is_the_alias_that_sets_it() -> None:
    effort = arm("effort-medium")
    assert (effort.alias, effort.body) == ("crew-analysis", {})


def test_the_arm_adds_to_the_body_without_changing_the_session_s() -> None:
    seen: list[dict[str, Any]] = []
    body = {"model": "crew-code-think", "messages": []}
    arm("think-off").wrap(echo(seen))(body)
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in body


def test_dropping_reasoning_touches_only_assistant_turns() -> None:
    seen: list[dict[str, Any]] = []
    messages = [
        {"role": "user", "content": "go", "reasoning_content": "not the model's"},
        {"role": "assistant", "content": "", "reasoning_content": "mine"},
    ]
    arm("reasoning-dropped").wrap(echo(seen))({"messages": messages})
    assert seen[0]["messages"] == [messages[0], {"role": "assistant", "content": ""}]
    assert messages[1]["reasoning_content"] == "mine"


def test_every_call_is_checked_not_only_the_first() -> None:
    spent = iter([0, 0, 5])
    armed = arm("think-off").wrap(lambda body: {"usage": {"reasoning_tokens": next(spent)}})
    armed({})
    armed({})
    with pytest.raises(ArmNotInEffect) as refused:
        armed({})
    assert refused.value.why == "arm_not_applied"
    assert armed.reasoning == [0, 0, 5]


def test_reasoning_tokens_are_read_where_the_proxy_puts_them() -> None:
    assert reasoning_tokens({"usage": {"completion_tokens_details": {"reasoning_tokens": 7}}}) == 7
    assert reasoning_tokens({"usage": {"reasoning_tokens": 3}}) == 3
    assert reasoning_tokens({}) == 0
