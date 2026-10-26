"""The workspace cap reaches crew's containers, and Grafana's answers become a run's numbers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tuning import grafana, session


def test_the_cap_reaches_the_sandbox_and_its_services(monkeypatch: pytest.MonkeyPatch) -> None:
    from crew_org.tools import container, sandbox

    monkeypatch.setattr(sandbox, "MEMORY", sandbox.MEMORY)
    monkeypatch.setattr(container, "MEMORY", container.MEMORY)
    session.cap("1536m")
    assert sandbox.MEMORY == container.MEMORY == "1536m"


@pytest.mark.parametrize("memory", ["1.5g", "1536", "0m", "1536m; rm"])
def test_a_cap_that_isnt_one_is_refused(memory: str) -> None:
    with pytest.raises(ValueError):
        session.cap(memory)


def test_session_needs_its_cap_first() -> None:
    assert session.main(["sprint-metrics-662"]) == 2


def series(*samples: float | str) -> dict[str, Any]:
    return {"data": {"result": [{"values": [[i, str(v)] for i, v in enumerate(samples)]}]}}


class FakeGrafana:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.asked: list[tuple[str, dict[str, str]]] = []

    def get(self, api: str, **params: str) -> Any:
        self.asked.append((api, params))
        if self.fail:
            raise httpx.HTTPStatusError(
                "no", request=httpx.Request("GET", "http://g/"), response=httpx.Response(403)
            )
        if api == "query":
            if "aborted" in params["query"]:
                return {"data": {"result": [{"value": [0, "1"]}]}}
            if "inter_token" in params["query"]:
                q = 0.2 if "0.95" in params["query"] else 0.05
            else:
                q = 9.5 if "0.95" in params["query"] else 1.25
            return {"data": {"result": [{"value": [0, str(q)]}]}}
        if "queue" in params["query"]:
            return series(0, 2, 1)
        if "cache_hit" in params["query"]:
            return series(0.5, 1.0, "NaN")
        return {"data": {"result": []}}


def test_the_runs_numbers_and_raw_series_are_kept(tmp_path: Path) -> None:
    fake = FakeGrafana()
    numbers = grafana.copy(tmp_path, 1000.0, 1600.0, fake)
    assert numbers["queue_max"] == 2.0
    assert numbers["cache_hit_mean"] == 0.75
    assert numbers["kv_use_max"] is None
    assert (numbers["ttft_p50_s"], numbers["ttft_p95_s"]) == (1.25, 9.5)
    assert (numbers["itl_p50_s"], numbers["decode_tps_p50"], numbers["aborted"]) == (
        0.05,
        20.0,
        1.0,
    )
    assert numbers["grafana"] is True
    assert any("[600s]" in p["query"] for a, p in fake.asked if a == "query")
    kept = json.loads((tmp_path / "grafana.json").read_text())
    assert set(kept["series"]) == {*grafana.SERIES, *grafana.WHOLE_RUN}


def test_grafana_that_cant_be_read_leaves_nulls_and_says_why_on_the_mac(tmp_path: Path) -> None:
    numbers = grafana.copy(tmp_path, 1000.0, 1600.0, FakeGrafana(fail=True))
    assert numbers["grafana"] is False
    assert all(v is None for k, v in numbers.items() if k != "grafana")
    assert (tmp_path / "grafana-error.txt").read_text() == "HTTPStatusError 403\n"


def test_missing_grafana_settings_are_a_handled_failure(tmp_path: Path) -> None:
    env = tmp_path / "grafana.env"
    env.write_text("GRAFANA_URL=\n")
    with pytest.raises(LookupError):
        grafana.Grafana.from_env(env)
