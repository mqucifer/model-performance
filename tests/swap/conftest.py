from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from swap.config import Config, Engine, load

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class FakeRunner:
    """Records each step. Results are scripted; by default every step succeeds."""

    ticks: bool = False
    remote_fails: set[str] = field(default_factory=set)  # a substring of the commands that fail
    answers_after: dict[str, int] = field(default_factory=dict)  # alias -> failed polls first
    never_answers: set[str] = field(default_factory=set)
    exited: set[str] = field(default_factory=set)  # containers docker inspect shows not running
    listed: bool = True
    command_result: int | BaseException = 0
    on_remote: Callable[[str], None] | None = None
    command_env: dict[str, str] = field(default_factory=dict)
    logs: str = "loading weights\n"  # what `docker logs` shows of the candidate
    steps: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    now: float = 0.0

    def say(self, message: str) -> None:
        self.messages.append(message)

    def ticks_running(self) -> bool:
        self.steps.append("ticks?")
        return self.ticks

    def remote(self, command: str, stdin: bytes | None = None) -> int:
        if "docker inspect" in command:
            container = command.split()[-4]
            self.steps.append(f"running? {container}")
            return 1 if container in self.exited else 0
        fed = ""
        if stdin is not None:  # which launch was sent, by its compose `name:`
            fed = next(
                f" <{line.split()[1]}"
                for line in stdin.decode().splitlines()
                if line.startswith("name:")
            )
        self.steps.append(f"ssh {command}{fed}")
        if self.on_remote:
            self.on_remote(command)
        return 1 if any(part in command for part in self.remote_fails) else 0

    def remote_output(self, command: str) -> tuple[int, str]:
        self.steps.append(f"ssh-out {command}")
        if "docker logs" in command:
            return 0, self.logs
        return 0, "spark-candidate\tExited (1)\tlmsysorg/sglang\n"

    def answers(self, alias: str, seed: bool) -> bool:
        self.steps.append(f"answers? {alias}" + (" seeded" if seed else ""))
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

    def run(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.steps.append(f"run {' '.join(argv)}")
        self.command_env = dict(env)
        if isinstance(self.command_result, BaseException):
            raise self.command_result
        return self.command_result

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now


@pytest.fixture
def config() -> Config:
    """The real config.toml, with each engine's launch read from the fixtures."""
    real = load()
    engines = {
        name: replace(engine, compose=Path(f"{name}.yaml")) for name, engine in real.engines.items()
    }
    return replace(real, infra_dir=FIXTURES, engines=engines)


def launch(config: Config, engine: Engine) -> str:
    return config.launch_path(engine).read_text()
