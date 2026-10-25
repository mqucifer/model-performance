"""Who carries the steps out: the real runner, and the dry one that only prints."""

from __future__ import annotations

import os
import secrets
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import httpx

from swap.config import Config

SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")
REMOTE_TIMEOUT_S = 600
CHECK_TIMEOUT_S = 60
COMMAND_GRACE_S = 30
# A process that is `crew tick`, run directly, by `uv run` or by the venv's python.
# Anchored at the start, so it matches neither its own pgrep, nor a shell or a
# watcher whose command line only mentions "crew tick", nor `swap ... -- crew tick`.
TICK_PATTERN = r"^([^ ]*/)?(uv run( -[^ ]*( [^ -][^ ]*)?)* |python[0-9.]* ([^ ]*/)?)?crew tick( |$)"


def ticks_running() -> bool:
    """A `crew tick` runs on this Mac, other than this process or its parent."""
    found = subprocess.run(["pgrep", "-f", TICK_PATTERN], capture_output=True, text=True)
    mine = {os.getpid(), os.getppid()}
    return any(int(pid) not in mine for pid in found.stdout.split())


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class RealRunner:
    """Over ssh to the Spark, and over HTTP to LiteLLM on :4000 only.

    The Spark's address and the LiteLLM key are read here and never printed:
    messages name the Spark as $SPARK_ADDR. The ssh user is ~/.ssh/config's.
    """

    def __init__(self, config: Config, hosts: dict[str, str], key: str) -> None:
        self.config = config
        self.target = hosts[config.addr_key]
        self.client = httpx.Client(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=CHECK_TIMEOUT_S,
        )

    say = staticmethod(say)
    ticks_running = staticmethod(ticks_running)

    def remote(self, command: str, stdin: bytes | None = None) -> int:
        say(f"  ssh ${self.config.addr_key}: {command}")
        try:
            done = subprocess.run(
                ["ssh", *SSH_OPTIONS, self.target, command],
                input=stdin if stdin is not None else b"",
                timeout=REMOTE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            say(f"  timed out after {REMOTE_TIMEOUT_S}s")
            return 124
        return done.returncode

    def answers(self, alias: str, seed: bool) -> bool:
        """One short completion through LiteLLM, seeded when the engine needs it.

        A completion, not a health endpoint: an engine has answered `/health`
        with 200 while failing every request (mqucifer/model-performance#4).
        Only the status is shown.
        """
        body: dict[str, object] = {
            "model": alias,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 1,
        }
        if seed:
            body["seed"] = secrets.randbelow(2**31)
        try:
            response = self.client.post("/v1/chat/completions", json=body)
        except httpx.HTTPError as error:
            say(f"  {alias} through LiteLLM: {type(error).__name__}")
            return False
        say(f"  {alias} through LiteLLM: {response.status_code}")
        return response.status_code == 200 and bool(response.json().get("choices"))

    def lists(self, alias: str) -> bool:
        try:
            response = self.client.get("/v1/models")
            response.raise_for_status()
        except httpx.HTTPError as error:
            say(f"  LiteLLM's models: {type(error).__name__}")
            return False
        return alias in {model["id"] for model in response.json().get("data", [])}

    def run(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        child = subprocess.Popen(list(argv), env={**os.environ, **env})
        try:
            return child.wait()
        except BaseException as interrupt:
            # Ctrl-C reached the child too, so it gets a moment to end itself.
            # SIGTERM or SIGHUP came to the swap only, so it's passed on now.
            try:
                if not isinstance(interrupt, KeyboardInterrupt):
                    child.terminate()
                child.wait(timeout=COMMAND_GRACE_S)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=COMMAND_GRACE_S)
                except subprocess.TimeoutExpired:
                    child.kill()
            raise

    sleep = staticmethod(time.sleep)
    clock = staticmethod(time.monotonic)


class DryRunner:
    """Prints every step and changes nothing. Checks pass as if all went well.

    The tick check is real: it only reads, and it's the one a dry run should catch.
    """

    def __init__(
        self,
        config: Config,
        launches: Mapping[str, Path],
        ticks: Callable[[], bool] | None = None,
    ) -> None:
        """`launches` maps each launch's text to its path in infra, to name what is sent."""
        self.config = config
        self.launches = launches
        self._ticks = ticks
        self._now = 0.0

    say = staticmethod(say)

    def ticks_running(self) -> bool:
        return (self._ticks or ticks_running)()

    def remote(self, command: str, stdin: bytes | None = None) -> int:
        fed = f"   < {self.launches.get(stdin.decode(), '?')}" if stdin is not None else ""
        say(f"  [dry-run] ssh ${self.config.addr_key}: {command}{fed}")
        return 0

    def answers(self, alias: str, seed: bool) -> bool:
        seeded = " with a seed" if seed else ""
        say(f"  [dry-run] POST {self.config.base_url}/v1/chat/completions model={alias}{seeded}")
        return True

    def lists(self, alias: str) -> bool:
        say(f"  [dry-run] GET {self.config.base_url}/v1/models has {alias}")
        return True

    def run(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        say(f"  [dry-run] {assignments} {shlex.join(argv)}")
        return 0

    def sleep(self, seconds: float) -> None:
        self._now += seconds

    def clock(self) -> float:
        return self._now


def read_secrets(config: Config, hosts_file: Path) -> tuple[dict[str, str], str]:
    """The Spark's address and the LiteLLM key, read without exporting them."""
    from crew_org.config import load_env

    hosts = load_env(hosts_file)
    if not hosts.get(config.addr_key):
        raise LookupError(f"{config.addr_key} not set in {hosts_file}")
    key = load_env(config.key_file).get(config.key_name)
    if not key:
        raise LookupError(f"{config.key_name} not set in {config.key_file}")
    return hosts, key
