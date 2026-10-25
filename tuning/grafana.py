"""The Spark's side of a concurrent run, read from Grafana and copied to the Mac.

Nothing calls the Spark: Alloy on the Home Assistant machine sends SGLang's metrics to
Grafana (mqucifer/infra#38), and these are the series of its "3 The Spark under load"
dashboard (`infra-spark-load`), plus SGLang's time to first token and draft acceptance.
Grafana keeps 7 days, so each run's raw series go to its records directory on the Mac,
and its numbers to `results/tuning.jsonl`.

The URL and the read token are `GRAFANA_URL` and `GRAFANA_READ_TOKEN` in infra's
`~/.config/infra/grafana.env` (or `$INFRA_GRAFANA_ENV`), read with `load_env` and never
printed.
"""

from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any

import httpx

DATASOURCE = "grafanacloud-prom"
JOB = '{job="prometheus.scrape.sglang"}'
STEP_S = 15

# What each number is: the dashboard's query, and how the run's samples become one number.
SERIES = {
    "queue_max": (f"sum(sglang_num_queue_reqs{JOB})", max),
    "running_max": (f"sum(sglang_num_running_reqs{JOB})", max),
    "cache_hit_mean": (f"max(sglang_cache_hit_rate{JOB})", statistics.fmean),
    "kv_use_max": (f"max(sglang_token_usage{JOB})", max),
    "spec_accept_mean": (f"max(sglang_spec_accept_length{JOB})", statistics.fmean),
    "gen_throughput_mean": (f"sum(sglang_gen_throughput{JOB})", statistics.fmean),
}
# Over the whole run, at its end: a quantile of the requests it made.
TTFT = (
    "histogram_quantile({q}, sum by (le)"
    " (increase(sglang_time_to_first_token_seconds_bucket{job}[{w}s])))"
)


def env_file() -> Path:
    return Path(os.environ.get("INFRA_GRAFANA_ENV", Path.home() / ".config/infra/grafana.env"))


class Grafana:
    def __init__(self, url: str, token: str) -> None:
        self.client = httpx.Client(
            base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=60
        )

    @classmethod
    def from_env(cls, path: Path | None = None) -> Grafana:
        from crew_org.config import load_env  # noqa: PLC0415

        env = load_env(path or env_file())
        missing = [k for k in ("GRAFANA_URL", "GRAFANA_READ_TOKEN") if not env.get(k)]
        if missing:
            raise LookupError(f"{', '.join(missing)} not set in {path or env_file()}")
        return cls(env["GRAFANA_URL"], env["GRAFANA_READ_TOKEN"])

    def get(self, api: str, **params: str) -> Any:
        response = self.client.get(
            f"/api/datasources/proxy/uid/{DATASOURCE}/api/v1/{api}", params=params
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()


def values(answer: dict[str, Any]) -> list[float]:
    """Every sample of every series in a Prometheus answer, NaN dropped."""
    found = []
    for series in answer.get("data", {}).get("result", []):
        points = series.get("values") or ([series["value"]] if "value" in series else [])
        for _, v in points:
            f = float(v)
            if f == f:
                found.append(f)
    return found


def read(
    grafana: Grafana, start: float, end: float
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """The run's numbers, and the raw answers they came from."""
    raw: dict[str, Any] = {}
    numbers: dict[str, float | None] = {}
    window = {"start": f"{start:.0f}", "end": f"{end:.0f}", "step": str(STEP_S)}
    for name, (query, reduce) in SERIES.items():
        raw[name] = {"query": query, **grafana.get("query_range", query=query, **window)}
        samples = values(raw[name])
        numbers[name] = round(reduce(samples), 3) if samples else None
    seconds = max(int(end - start), STEP_S)
    for name, q in (("ttft_p50_s", 0.5), ("ttft_p95_s", 0.95)):
        query = TTFT.format(q=q, job=JOB, w=seconds)
        raw[name] = {"query": query, **grafana.get("query", query=query, time=f"{end:.0f}")}
        samples = values(raw[name])
        numbers[name] = round(samples[0], 3) if samples else None
    return numbers, raw


def copy(out: Path, start: float, end: float, grafana: Grafana | None = None) -> dict[str, Any]:
    """The run's Spark numbers, with `grafana` saying whether they were read.

    The raw answers go to `out/grafana.json`. A Grafana that can't be read leaves the
    numbers null and says why in `out/grafana-error.txt`, never in the row.
    """
    nothing: dict[str, Any] = dict.fromkeys([*SERIES, "ttft_p50_s", "ttft_p95_s"])
    own = grafana is None
    try:
        grafana = grafana or Grafana.from_env()
        numbers, raw = read(grafana, start, end)
    except (LookupError, OSError, httpx.HTTPError, ValueError, KeyError) as error:
        # Only the kind of failure and its status: never the URL's host or the token.
        status = getattr(getattr(error, "response", None), "status_code", "")
        (out / "grafana-error.txt").write_text(
            f"{type(error).__name__} {status}\n", encoding="utf-8"
        )
        return {**nothing, "grafana": False}
    finally:
        if own and grafana is not None:
            grafana.close()
    (out / "grafana.json").write_text(
        json.dumps({"start": start, "end": end, "step_s": STEP_S, "series": raw}, indent=1),
        encoding="utf-8",
    )
    return {**numbers, "grafana": True}
