"""The equal-load window and output by running count, from a run's rows and copied series."""

from __future__ import annotations

import json
from pathlib import Path

from tuning import equal_load


def test_the_window_ends_at_the_first_session_to_finish(tmp_path: Path) -> None:
    (tmp_path / "tuning.jsonl").write_text(
        json.dumps({"run": "B", "at": "2026-10-26T10:00:00+00:00"}) + "\n"
    )
    rows = [
        {"batch": "B", "at": "2026-10-26T10:00:00+00:00", "wall_s": 400.0},
        {"batch": "B", "at": "2026-10-26T10:00:03+00:00", "wall_s": 300.0},
        {"batch": "OTHER", "at": "2026-10-26T09:00:00+00:00", "wall_s": 10.0},
    ]
    (tmp_path / "benchmark.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    start, end = equal_load.window("B", tmp_path)
    assert end - start == 303.0


def test_output_is_grouped_by_running_count() -> None:
    def series(points: list[tuple[int, str]]) -> dict:
        return {"data": {"result": [{"values": [[t, v] for t, v in points]}]}}

    found = equal_load.by_running(
        {
            "running_max": series([(0, "6"), (15, "6"), (30, "5"), (45, "NaN")]),
            "gen_throughput_mean": series([(0, "100"), (15, "110"), (30, "90"), (45, "80")]),
        }
    )
    assert found == {5: (1, 90.0), 6: (2, 105.0)}
