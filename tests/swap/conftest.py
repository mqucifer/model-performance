from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from swap.config import Config, load

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class FakeRunner:
    """Records each step. Results are scripted; by default every step succeeds."""

    ticks: bool = False
    remote_fails: set[str] = field(default_factory=set)  # a substring of the commands that fail
    answers_after: dict[str, int] = field(default_factory=dict)  # alias -> failed polls first
    never_answers: set[str] = field(default_factory=set)
    listed: bool = True
    command_result: int | BaseException = 0
    on_remote: Callable[[str], None] | None = None
    steps: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    now: float = 0.0

    def say(self, message: str) -> None:
        self.messages.append(message)

    def ticks_running(self) -> bool:
        self.steps.append("ticks?")
        return self.ticks

    def remote(self, command: str, stdin: bytes | None = None) -> int:
        self.steps.append(f"ssh {command}" + (" <stdin" if stdin is not None else ""))
        if self.on_remote:
            self.on_remote(command)
        return 1 if any(part in command for part in self.remote_fails) else 0

    def answers(self, alias: str) -> bool:
        self.steps.append(f"answers? {alias}")
        if alias in self.never_answers:
            return False
        left = self.answers_after.get(alias, 0)
        if left:
            self.answers_after[alias] = left - 1
            return False
        return True

    def lists(self, alias: str) -> bool:
        self.steps.append(f"lists? {alias}")
        return self.listed

    def run(self, argv: Sequence[str]) -> int:
        self.steps.append(f"run {' '.join(argv)}")
        if isinstance(self.command_result, BaseException):
            raise self.command_result
        return self.command_result

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now


@pytest.fixture
def config() -> Config:
    return replace(load(), infra_dir=FIXTURES.parent, compose=Path("fixtures/compose.yaml"))


@pytest.fixture
def compose_text() -> str:
    return (FIXTURES / "compose.yaml").read_text()
