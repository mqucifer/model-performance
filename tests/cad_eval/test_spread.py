"""The spread of repeated runs (mqucifer/model-performance#27): Wilson intervals, the
staged rule set before the runs, which cells to extend, and `--repeat`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cad_eval import run as cad
from cad_eval import spread
from cad_eval.spread import Cell, cells, extend, needed, verdict, wilson


def row(case: str, arm: str | None, fault: str | None, n: int = 0, **kw: Any) -> dict[str, Any]:
    return {
        "suite": "cad_eval",
        "case": case,
        "arm": arm,
        "fault": fault,
        "at": f"2026-10-26T0{n % 10}:00:00+00:00",
        "run": f"r{case}{arm}{n}",
        "concurrency": 4,
        "stop": None if fault is None else "call_cap",
        "ending": "done",
        "calls_to_first_compile": 3,
        **kw,
    }


def cell(passes: int, n: int, arm: str | None = None) -> Cell:
    return Cell(
        "spur-gear",
        arm,
        [row("spur-gear", arm, None if k < passes else "budget", k) for k in range(n)],
    )


def test_wilson_matches_its_known_values() -> None:
    assert wilson(0, 3) == pytest.approx((0.0, 0.5615), abs=1e-3)
    assert wilson(3, 3) == pytest.approx((0.4385, 1.0), abs=1e-3)
    assert wilson(0, 5) == pytest.approx((0.0, 0.4345), abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("passes", "n", "state"),
    [
        (0, 1, "short"),
        (0, 3, "fail"),
        (3, 3, "pass"),
        (1, 3, "open"),
        (2, 3, "open"),
        (1, 5, "fail"),
        (4, 5, "pass"),
        (2, 5, "open"),
        (3, 5, "open"),
    ],
)
def test_a_cells_state_follows_the_rule_set_before_the_runs(
    passes: int, n: int, state: str
) -> None:
    assert cell(passes, n).state() == state


def test_a_case_is_a_gap_closed_or_noise() -> None:
    assert verdict([cell(0, 3, a) for a in spread.ARMS]) == "gap"
    assert (
        verdict([cell(0, 3), cell(0, 3, "skill"), cell(3, 3, "refs"), cell(1, 3, "skill-refs")])
        == "closed"
    )
    assert (
        verdict([cell(0, 3), cell(1, 3, "skill"), cell(0, 3, "refs"), cell(0, 3, "skill-refs")])
        == "noise"
    )
    assert (
        verdict([cell(0, 3), cell(0, 1, "skill"), cell(0, 3, "refs"), cell(0, 3, "skill-refs")])
        == "short"
    )


def test_only_cells_that_could_change_a_verdict_are_extended() -> None:
    two = [cell(0, 3), cell(2, 3, "skill"), cell(0, 3, "refs"), cell(0, 3, "skill-refs")]
    assert [c.arm for c in extend(two)] == ["skill"]
    ones = [cell(0, 3), cell(1, 3, "skill"), cell(1, 3, "refs"), cell(0, 3, "skill-refs")]
    assert [c.arm for c in extend(ones)] == ["skill", "refs"]
    # A 1 of 3 beside a 2 of 3 can't make the case a gap: only the 2 of 3 is extended.
    mixed = [cell(1, 3), cell(2, 3, "skill"), cell(0, 3, "refs"), cell(0, 3, "skill-refs")]
    assert [c.arm for c in extend(mixed)] == ["skill"]
    assert extend([cell(0, 3, a) for a in spread.ARMS]) == []


def test_harness_and_infra_runs_and_old_rows_are_not_samples() -> None:
    rows = [
        row("bolt-nut", None, None, 1),
        row("bolt-nut", None, "tool", 2),
        row("bolt-nut", None, "infra", 3),
        {**row("bolt-nut", None, "model", 4), "at": "2026-10-25T17:00:00+00:00"},
        {**row("bolt-nut", None, "model", 5), "concurrency": None},
        row("bolt-nut", "refs", "budget", 6),
        row("spacer", None, None, 7),
    ]
    found = cells(rows)
    assert found[("bolt-nut", None)].n == 1 and found[("bolt-nut", "refs")].n == 1
    assert ("spacer", None) not in found


def test_needed_counts_runs_to_the_screen_and_then_the_extensions() -> None:
    rows = [row(c, a, "budget", k) for c in spread.CASES for a in spread.ARMS for k in range(3)]
    assert needed(rows) == {}
    rows = [r for r in rows if not (r["case"] == "m8-bolt" and r["arm"] == "skill")]
    assert needed(rows) == {("m8-bolt", "skill"): 3}
    rows += [row("m8-bolt", "skill", None, k) for k in range(2)]
    rows += [row("m8-bolt", "skill", "budget", 9)]
    assert needed(rows) == {("m8-bolt", "skill"): 2}


def test_the_report_says_n3_is_a_screen_and_gives_each_cell(tmp_path: Path) -> None:
    rows = [row(c, a, "budget", k) for c in spread.CASES for a in spread.ARMS for k in range(3)]
    text = spread.report(rows, tmp_path)
    assert "n = 3 is a screen, not a measurement" in text
    assert "| spur-gear | **gap** |" in text
    assert "0/3 (0%–56%) fail" in text


def test_repeat_runs_each_case_n_times_with_its_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.cad_eval.test_arms import ready  # noqa: PLC0415

    monkeypatch.setenv("HOME", str(tmp_path))
    evaluated = ready(monkeypatch, ticking=False)
    calls: list[Any] = []
    original = cad.evaluate

    def keep(p: Any, *a: Any, **kw: Any) -> Any:
        calls.append((p.name, kw.get("sample")))
        return original(p, *a, **kw)

    monkeypatch.setattr(cad, "evaluate", keep)
    assert cad.main(["m8-bolt", "spur-gear", "--repeat", "2", "--arm", "refs"]) == 0
    assert sorted(calls) == [("m8-bolt", 1), ("m8-bolt", 2), ("spur-gear", 1), ("spur-gear", 2)]
    assert len(evaluated) == 4
    with pytest.raises(SystemExit):
        cad.main(["spacer", "--repeat", "2"])


def test_each_runs_serving_is_its_rows_or_its_time() -> None:
    assert (
        spread.served_on({"serving": "sglang-0.5.22", "at": "2026-10-25T20:00"}) == "sglang-0.5.22"
    )
    assert spread.served_on({"at": "2026-10-26T06:00:00+00:00"}) == "sglang-0.5.20"
    assert spread.served_on({"at": "2026-10-26T15:30:00+00:00"}) == "sglang-0.5.22"


def test_the_report_names_the_serving_versions(tmp_path: Path) -> None:
    rows = [row("spur-gear", None, "budget", k) for k in range(3)]
    rows.append({**row("spur-gear", "refs", None, 9), "serving": "sglang-0.5.22"})
    text = spread.report(rows, tmp_path)
    assert "v0.5.20 to v0.5.22" in text and "sglang-0.5.22 ×1" in text
