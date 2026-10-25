"""The one way a model is called: LiteLLM on the Mac's :4000, with the builders' key.

A `Sender` is what crew's session takes as `send`: a request body in, the
response's JSON out. It reads the key once, inside this process, from the
builders' env file, and never shows it. It counts its calls and refuses the one
past its cap, so a run ends inside its budget: crew's session ends it as
interrupted, the same as any failed call.

It also notes, before each call, whether a `crew tick` is running: the tick
shares the 27B, so a run's wall time and model time depend on it, and runs are
compared like for like. The Spark's own queue isn't read: nothing probes SGLang
directly, and LiteLLM's replies don't carry it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from common.config import Settings
from swap.runners import ticks_running

DEFAULT_TIMEOUT_S = 3600.0


class CallCapReached(RuntimeError):
    """The run has made every call its budget allows."""


class Sender:
    def __init__(
        self,
        settings: Settings,
        key: str,
        *,
        cap: int | None = None,
        alias: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
        tick: Callable[[], bool] = ticks_running,
    ) -> None:
        self.cap = settings.call_cap if cap is None else cap
        # A candidate's alias in place of the role's, so a swap measures the same session.
        self.alias = alias
        self.calls = 0
        self.models: set[str] = set()
        self._tick = tick
        # Calls made while a tick ran, and whether one was seen at all.
        self.tick_calls = 0
        self.tick_seen = False
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
            transport=transport,
        )

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.calls >= self.cap:
            raise CallCapReached(f"the run's cap of {self.cap} calls is reached")
        if self.alias:
            body = {**body, "model": self.alias}
        self.models.add(str(body.get("model")))
        self.calls += 1
        if self.ticking():
            self.tick_calls += 1
        response = self._client.post("/chat/completions", json=body)
        if response.status_code >= 400:
            # The status only: a body can echo the request, and this text reaches the record.
            raise httpx.HTTPStatusError(
                f"LiteLLM answered {response.status_code}",
                request=response.request,
                response=response,
            )
        result: dict[str, Any] = response.json()
        return result

    def ticking(self) -> bool:
        """Whether a `crew tick` runs now; remembered once seen."""
        now = self._tick()
        self.tick_seen = self.tick_seen or now
        return now

    def lists(self, alias: str) -> bool:
        """Whether the proxy knows `alias` for this key: a check that costs no model call."""
        response = self._client.get("/models")
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"LiteLLM answered {response.status_code} for its models",
                request=response.request,
                response=response,
            )
        return alias in {model.get("id") for model in response.json().get("data", [])}

    def close(self) -> None:
        self._client.close()


def builders_key(settings: Settings) -> str:
    """The builders' key, read inside this process; nothing is exported or shown."""
    from crew_org.config import load_env  # noqa: PLC0415

    key = load_env(settings.key_file).get(settings.key_name)
    if not key:
        raise LookupError(f"{settings.key_name} not set in {settings.key_file}")
    return key
