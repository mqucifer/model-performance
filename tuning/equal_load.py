"""A concurrent run's Spark numbers while all its sessions ran, so settings compare at equal load.

    uv run python -m tuning.equal_load 20261026T105927Z 20261026T121036Z

A batch is ragged: its short cases finish first, and a long one can run its last
minutes alone, so whole-run numbers mix loads (mqucifer/model-performance#7). This reads
two things for the window from the batch's start to its first session's end, when all N
ran:

- SGLang's TTFT, ITL and end-to-end quantiles over that window, from Grafana;
- output tokens per second, by how many requests were running, from the run's own
  copied series (`grafana.json` in its records), at its 15 s step.

It prints them; nothing is written. Nothing calls the Spark.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from common.config import load
from tuning.grafana import JOB, QUANTILE, Grafana, values

METRICS = {
    "ttft": "sglang_time_to_first_token_seconds",
    "itl": "sglang_inter_token_latency_seconds",
    "e2e": "sglang_e2e_request_latency_seconds",
}


def window(run: str, results: Path) -> tuple[float, float]:
    """The batch's start, and its first session's end, from the results rows."""
    tuning = [json.loads(line) for line in (results / "tuning.jsonl").read_text().splitlines()]
    row = next(r for r in tuning if r["run"] == run)
    start = datetime.fromisoformat(row["at"]).timestamp()
    sessions = [
        json.loads(line)
        for line in (results / "benchmark.jsonl").read_text().splitlines()
        if f'"batch": "{run}"' in line
    ]
    ends = [datetime.fromisoformat(s["at"]).timestamp() + s["wall_s"] for s in sessions]
    return start, min(ends)


def quantiles(grafana: Grafana, start: float, end: float) -> dict[str, float | None]:
    seconds = int(end - start)
    found: dict[str, float | None] = {}
    for name, metric in METRICS.items():
        for q in (0.5, 0.95):
            query = (
                QUANTILE.replace("{q}", str(q))
                .replace("{metric}", metric)
                .replace("{job}", JOB)
                .replace("{w}", str(seconds))
            )
            got = values(grafana.get("query", query=query, time=f"{end:.0f}"))
            found[f"{name}_p{int(q * 100)}_s"] = round(got[0], 3) if got else None
    itl = found["itl_p50_s"]
    found["decode_tps_p50"] = round(1 / itl, 1) if itl else None
    return found


def by_running(series: dict[str, Any]) -> dict[int, tuple[int, float]]:
    """Output tok/s by running count: (samples, mean)."""

    def points(name: str) -> dict[int, float]:
        found = {}
        for s in series[name]["data"]["result"]:
            for t, v in s["values"]:
                if float(v) == float(v):
                    found[int(t)] = float(v)
        return found

    running, output = points("running_max"), points("gen_throughput_mean")
    found: dict[int, list[float]] = {}
    for t, n in running.items():
        if t in output:
            found.setdefault(int(n), []).append(output[t])
    return {n: (len(v), round(statistics.fmean(v), 1)) for n, v in sorted(found.items())}


def main(argv: list[str] | None = None) -> int:
    runs = list(sys.argv[1:] if argv is None else argv)
    if not runs:
        print(__doc__, file=sys.stderr)
        return 2
    settings = load()
    results = Path(__file__).parents[1] / "results"
    grafana = Grafana.from_env()
    try:
        for run in runs:
            start, end = window(run, results)
            out = settings.records_dir / "tuning" / "concurrent" / run / "grafana.json"
            series = json.loads(out.read_text())["series"]
            print(f"{run}: all running for {end - start:.0f} s", quantiles(grafana, start, end))
            print("  output tok/s by running (samples, mean):", by_running(series))
    finally:
        grafana.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
