"""The arms: one setting changed against the baseline (mqucifer/model-performance#5).

    uv run replay sprint-metrics-567 --arm think-off
    uv run replay sprint-metrics-567 --arm budget-128

An arm is what's sent, or how the session runs, and nothing else: a LiteLLM alias,
fields added to each request's body, the reasoning the history sends back, or where
the session compacts. It wraps the run's `Sender`, so `common.litellm` is the one way
a model is called, unchanged. A row without an arm is the baseline.

Each arm names the request field and value it sets, because "effort" and "budget"
mean different things in LiteLLM and SGLang:

- `think-off`: `chat_template_kwargs: {enable_thinking: false}` in each body, on
  `crew-code-think`'s sampling. Qwen's template then writes no thinking.
- `effort-medium`: the `crew-analysis` alias, whose LiteLLM config sends SGLang
  `reasoning_effort: medium` (with `allowed_openai_params`, or `drop_params` strips
  it). It's `crew-code-think` but for that and its 1800 s timeout. Sent as a request
  field instead, it would depend on whether a request may override an alias's
  setting, which a run can't see.
- `reasoning-dropped`: every assistant turn's `reasoning_content` left out of what's
  sent (crew#813). The session keeps it; only the request loses it.
- `compact-<k>`: the session compacts at k thousand estimated tokens, not crew's 125k.
  The form is crew's at the pin. The records say on which calls it fired; never
  firing is a finding, not a failure.
- `budget-<n>`: `custom_params: {thinking_budget: n}` in each body. SGLang enforces
  it only when launched with `--enable-strict-thinking` or
  `--enable-custom-logit-processor`; without either it's a hint to the template.

An arm whose setting can be seen in the answer is checked on every call: thinking
off must spend no reasoning tokens, and a budget no more than its own. The first
call that breaks it ends the run as `refused`, with why in a word
(`arm_not_applied`, `budget_unenforced`): the setting didn't reach the model, so the
run would measure the baseline under another name.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# A budget's answer may close its thinking a few tokens past the budget: the end tag.
BUDGET_SLACK = 8


class ArmNotInEffect(RuntimeError):
    """An answer shows the arm's setting didn't reach the model; `why` in a word."""

    def __init__(self, why: str, detail: str) -> None:
        super().__init__(f"{why}: {detail}")
        self.why = why
        self.detail = detail


class UnknownArm(ValueError):
    pass


@dataclass(frozen=True)
class Arm:
    name: str
    # The alias called in place of the role's, or None for the role's own.
    alias: str | None = None
    # Fields added to each request's body.
    body: dict[str, Any] = field(default_factory=dict)
    drop_reasoning: bool = False
    compact_at: int | None = None
    # The most reasoning tokens a call may spend, if the arm sets it.
    max_reasoning: int | None = None
    # The word a call over `max_reasoning` ends the run with.
    over: str = "arm_not_applied"

    def describe(self) -> dict[str, Any]:
        """What the arm sets, whole, for the run's records."""
        return {
            "name": self.name,
            "alias": self.alias,
            "body": self.body,
            "drop_reasoning": self.drop_reasoning,
            "compact_at": self.compact_at,
            "max_reasoning": self.max_reasoning,
        }

    def wrap(self, send: Callable[[dict[str, Any]], dict[str, Any]]) -> Armed:
        return Armed(self, send)


FIXED = {
    "think-off": Arm(
        "think-off",
        body={"chat_template_kwargs": {"enable_thinking": False}},
        max_reasoning=0,
    ),
    "effort-medium": Arm("effort-medium", alias="crew-analysis"),
    "reasoning-dropped": Arm("reasoning-dropped", drop_reasoning=True),
}
SIZED = re.compile(r"(compact|budget)-(\d+)")
NAMES = (*FIXED, "compact-<k>", "budget-<n>")


def arm(name: str) -> Arm:
    if name in FIXED:
        return FIXED[name]
    sized = SIZED.fullmatch(name)
    if not sized or int(sized[2]) <= 0:
        raise UnknownArm(f"no arm {name!r}; one of: {', '.join(NAMES)}")
    kind, n = sized[1], int(sized[2])
    if kind == "compact":
        return Arm(name, compact_at=n * 1000)
    return Arm(
        name,
        body={"custom_params": {"thinking_budget": n}},
        max_reasoning=n + BUDGET_SLACK,
        over="budget_unenforced",
    )


def reasoning_tokens(response: dict[str, Any]) -> int:
    """An answer's reasoning tokens, wherever the proxy puts them."""
    usage = response.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return int(usage.get("reasoning_tokens") or details.get("reasoning_tokens") or 0)


class Armed:
    """A `send` with the arm applied to each request, and each answer checked against it."""

    def __init__(self, arm: Arm, send: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.arm = arm
        self._send = send
        # Each call's reasoning tokens, in order: the records' per-call view.
        self.reasoning: list[int] = []

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        body = {**body, **self.arm.body}
        if self.arm.drop_reasoning:
            body["messages"] = [
                {k: v for k, v in m.items() if k != "reasoning_content"}
                if m.get("role") == "assistant"
                else m
                for m in body.get("messages", [])
            ]
        response = self._send(body)
        spent = reasoning_tokens(response)
        self.reasoning.append(spent)
        limit = self.arm.max_reasoning
        if limit is not None and spent > limit:
            raise ArmNotInEffect(
                self.arm.over,
                f"call {len(self.reasoning)} spent {spent} reasoning tokens, over {limit}",
            )
        return response
