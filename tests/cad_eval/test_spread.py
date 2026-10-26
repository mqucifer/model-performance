"""The spread of repeated runs (mqucifer/model-performance#27): Wilson intervals, the
staged rule set before the runs, which cells to extend, and `--repeat`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cad_eval import run as cad
from cad_eval import spread
from cad_eval.spread import Cell, cells, extend, verdict, wilson


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


def test_needed_is_the_decisive_runs_one_per_cell() -> None:
    assert spread.needed(today()) == {cell: 1 for cell in spread.plan(today())}
    rows = [row(c, a, "budget", k) for c in spread.CASES for a in spread.ARMS for k in range(3)]
    assert spread.needed(rows) == {}  # every case a gap: nothing left to decide


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


def today() -> list[dict[str, Any]]:
    """The four cases as they stood on 2026-10-26 at 17:30Z, as rows."""
    shape = {
        "spur-gear": {None: (1, 1), "skill": (0, 1), "refs": (1, 3), "skill-refs": (0, 1)},
        "m8-bolt": {None: (0, 1), "skill": (1, 1), "refs": (0, 3), "skill-refs": (0, 1)},
        "gear-pair": {None: (0, 2), "skill": (0, 1), "refs": (0, 1), "skill-refs": (0, 1)},
        "bolt-nut": {None: (0, 3), "skill": (0, 1), "refs": (0, 1), "skill-refs": (1, 1)},
    }
    rows = []
    for case, arms in shape.items():
        for arm, (passes, n) in arms.items():
            rows += [row(case, arm, None if k < passes else "budget", k) for k in range(n)]
    return rows


def test_spur_gear_refs_at_one_of_three_needs_no_more_runs_once_a_pass_rules_out_gap() -> None:
    plan = spread.plan(today(), gap_by_pass=True)
    assert ("spur-gear", "refs") not in plan
    # As written, a 1/3 cell can still be extended to 1/5 and make its case a gap, so
    # its runs would still decide gap or noise.
    assert ("spur-gear", "refs") in spread.plan(today())


@pytest.mark.parametrize("gap_by_pass", [False, True])
def test_gear_pair_runs_until_a_pass_or_every_cell_is_at_nought_of_three(gap_by_pass: bool) -> None:
    rows = today()
    first = [c for c in spread.plan(rows, gap_by_pass) if c[0] == "gear-pair"]
    assert first[0] == ("gear-pair", None) and len(first) == 4
    # Every gear-pair cell at 0/3: the case is a gap, and no run of it is decisive.
    rows += [row("gear-pair", None, "budget", 7)]
    rows += [
        row("gear-pair", a, "budget", k) for a in ("skill", "refs", "skill-refs") for k in (8, 9)
    ]
    assert not [c for c in spread.plan(rows, gap_by_pass) if c[0] == "gear-pair"]
    # A pass in one of its cells instead keeps that cell going (it could reach 3/3).
    rows = today() + [row("gear-pair", "refs", None, 7)]
    assert ("gear-pair", "refs") in spread.plan(rows, gap_by_pass)


def test_a_closed_case_needs_no_more_runs() -> None:
    rows = today() + [row("m8-bolt", "skill", None, k) for k in (7, 8)]
    assert spread.verdict([spread.cells(rows)[("m8-bolt", a)] for a in spread.ARMS]) == "closed"
    assert not [c for c in spread.plan(rows) if c[0] == "m8-bolt"]


def test_a_cell_stops_once_it_can_no_longer_change_its_verdict() -> None:
    # bolt-nut's skill cell at 0/2 can still reach 1/3 only: under "a pass rules out
    # gap" (bolt-nut has a pass) it can't change anything, so it stops.
    rows = today() + [row("bolt-nut", "skill", "budget", 7)]
    assert ("bolt-nut", "skill") not in spread.plan(rows, gap_by_pass=True)
