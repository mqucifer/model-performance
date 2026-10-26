"""The spread of repeated runs: gears and threads, arm by arm (mqucifer/model-performance#27).

    uv run python -m cad_eval.spread                    # the report, from the rows
    uv run python -m cad_eval.spread --measure-capped   # first: the capped runs' last files

One run per case can't tell a gap from noise where runs vary most, so the four gear
and thread cases run several times in each arm, and this reports the spread, from the
rows in `results/cad_eval.jsonl` and each run's records:

- each cell (a case in an arm): its passes out of n, with a 95% Wilson interval;
- each check's pass rate over the cell's runs that reached `done`;
- where each run ended: its fault class, and its first failing check;
- the call of its first compiling part, as a median and a range.

A run that is the harness's own fault (`tool`) or the infrastructure's (`infra`) isn't
a sample of the model, and is left out. A run that hits the call cap counts as not
passing: it **doesn't finish in 20 calls**, which isn't the same as "can't". With
`--measure-capped`, its last files are measured in the container, offline, so the
report can say which checks it had passed when it stopped.

**The decision rule, set before the runs** (the operator, 2026-10-26). Sampling is
staged to save the Spark: three runs per cell first, counting the runs already made.
**n = 3 is a screen, not a measurement.**
- **A cell fails** at 0 of 3, or at no more than 1 of 5. **A cell passes** at 3 of 3,
  or at least 4 of 5. Anything else is open.
- **A case is a gap** if every arm's cell fails: a candidate for training or a tool.
  **It's closed** if any arm's cell passes: knowledge closes it. **Anything else is
  noise.**
- A noisy case gets two more runs only in the cells that could change its verdict: a
  cell at 2 of 3, which could reach 4 of 5, or a cell at 1 of 3 when every other cell
  fails or is at 1 of 3, which could all end at no more than 1 of 5.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.results import RESULTS

CASES = ("spur-gear", "m8-bolt", "gear-pair", "bolt-nut")
ARMS = (None, "skill", "refs", "skill-refs")
# The harder cases' runs from the 21-case baseline on: the same prompt and checks.
SINCE = "2026-10-25T19"
Z = 1.959964  # 95%


def wilson(passes: int, n: int) -> tuple[float, float]:
    """The 95% Wilson score interval for `passes` of `n`."""
    if n == 0:
        return 0.0, 1.0
    p = passes / n
    centre = (p + Z**2 / (2 * n)) / (1 + Z**2 / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / (1 + Z**2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Cell:
    case: str
    arm: str | None
    runs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.runs)

    @property
    def passes(self) -> int:
        return sum(r["fault"] is None for r in self.runs)

    def state(self) -> str:
        """`pass`, `fail` or `open` by the rule; `short` with fewer than three runs."""
        if self.n < 3:
            return "short"
        if self.n < 5:
            if self.passes == self.n:
                return "pass"
            return "fail" if self.passes == 0 else "open"
        if self.passes >= self.n - 1:
            return "pass"
        return "fail" if self.passes <= 1 else "open"


def cells(rows: list[dict[str, Any]], cases: tuple[str, ...] = CASES) -> dict[tuple, Cell]:
    found = {(c, a): Cell(c, a) for c in cases for a in ARMS}
    for r in rows:
        key = (r.get("case"), r.get("arm"))
        if key not in found or str(r.get("at", "")) < SINCE or r.get("suite") != "cad_eval":
            continue
        if r.get("arm") is None and r.get("concurrency") is None:
            continue  # the first five's rows, before the parallel runner
        if r.get("fault") in ("tool", "infra"):
            continue  # not a sample of the model
        found[key].runs.append(r)
    return found


def verdict(case_cells: list[Cell]) -> str:
    """A case's verdict over its arms: `gap`, `closed`, `noise`, or `short`."""
    states = [c.state() for c in case_cells]
    if "pass" in states:
        return "closed"
    if "short" in states:
        return "short"
    if all(s == "fail" for s in states):
        return "gap"
    return "noise"


def extend(case_cells: list[Cell]) -> list[Cell]:
    """The cells of a noisy case that two more runs could move to a verdict."""
    if verdict(case_cells) != "noise":
        return []
    found = []
    for cell in case_cells:
        if cell.n != 3:
            continue
        others = [c for c in case_cells if c is not cell]
        if (
            cell.passes == 2
            or cell.passes == 1
            and all(c.state() == "fail" or c.passes <= 1 for c in others)
        ):
            found.append(cell)
    return found


def _futures(state: tuple[tuple[int, int], ...], gap_by_pass: bool) -> list[tuple]:
    """Every way a case's cells can finish, by the rule: each cell's remaining results
    (to three, then to five where `extend` picks it) and the verdict they end in.

    `state` is each cell's (passes, n). With `gap_by_pass`, a case with a pass in any
    run is never a gap, so no cell is extended to make it one (a reading of the rule,
    not the rule as written: see `decisive`).
    """
    import itertools  # noqa: PLC0415

    def cell(passes: int, n: int, k: int) -> Cell:
        runs = [{"fault": None}] * passes + [{"fault": "budget"}] * (n - passes)
        return Cell("x", k, runs)  # type: ignore[arg-type]

    fill = [max(0, 3 - n) for _, n in state]
    found = []
    for first in itertools.product(*[list(itertools.product((1, 0), repeat=f)) for f in fill]):
        at3 = [(p + sum(r), n + len(r)) for (p, n), r in zip(state, first, strict=True)]
        cells_at3 = [cell(p, n, k) for k, (p, n) in enumerate(at3)]
        chosen = {c.arm for c in extend(cells_at3)}
        if gap_by_pass and any(p for p, _ in at3):
            chosen = {c.arm for c in cells_at3 if c.arm in chosen and c.passes == 2}
        # A cell already past three was extended: it goes on to five.
        chosen |= {k for k, (_, n) in enumerate(at3) if 3 < n < 5}
        more = [5 - at3[k][1] if k in chosen else 0 for k in range(len(state))]
        for second in itertools.product(*[list(itertools.product((1, 0), repeat=m)) for m in more]):
            final = [
                cell(p + sum(r), n + len(r), k)
                for k, ((p, n), r) in enumerate(zip(at3, second, strict=True))
            ]
            results = tuple(a + b for a, b in zip(first, second, strict=True))
            found.append((results, verdict(final)))
    return found


def decisive(case_cells: list[Cell], gap_by_pass: bool = False) -> list[Cell]:
    """The cells whose next run could change their case's final verdict: some sequence of
    their remaining results, the other cells' held the same, ends in another verdict."""
    state = tuple((c.passes, c.n) for c in case_cells)
    futures = _futures(state, gap_by_pass)
    found = []
    for k, cell_ in enumerate(case_cells):
        groups: dict[tuple, set[str]] = {}
        for results, end in futures:
            others = results[:k] + results[k + 1 :]
            groups.setdefault(others, set()).add(end)
        moves = any(len(ends) > 1 for ends in groups.values())
        has_next = any(len(results[k]) > 0 for results, _ in futures)
        if moves and has_next:
            found.append(cell_)
    return found


def plan(rows: list[dict[str, Any]], gap_by_pass: bool = False) -> list[tuple[str, str | None]]:
    """The decisive runs, one per cell, in order: gear-pair's cells first (the one case
    still open on gap or not), then the cells that could decide another case. Re-plan
    after every run, so a cell stops at its first deciding result."""
    found = cells(rows)
    order = ["gear-pair", *[c for c in CASES if c != "gear-pair"]]
    return [
        (c.case, c.arm)
        for case in order
        for c in decisive([found[(case, arm)] for arm in ARMS], gap_by_pass)
    ]


def needed(rows: list[dict[str, Any]], gap_by_pass: bool = False) -> dict[tuple, int]:
    """The decisive runs only, one per cell (`plan`): re-plan after each."""
    return {cell: 1 for cell in plan(rows, gap_by_pass)}


# When production serving moved to SGLang v0.5.22 (the operator, 2026-10-26).
V0522_AT = "2026-10-26T14:45"


def served_on(row: dict[str, Any]) -> str:
    """A run's serving version: its row's, or for a row from before the field, by its time."""
    if row.get("serving"):
        return str(row["serving"])
    return "sglang-0.5.22" if str(row.get("at", "")) >= V0522_AT else "sglang-0.5.20"


def checks_of(record: Path) -> list[dict[str, Any]] | None:
    """A run's checks: at `done` from `checks.json`, at the cap from its last files."""
    for name in ("checks.json", "capped_checks.json"):
        path = record / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get("checks")
    return None


def report(rows: list[dict[str, Any]], records: Path) -> str:
    """The spread, as markdown: the verdicts, then each cell."""
    found = cells(rows)
    lines = [
        "**n = 3 is a screen, not a measurement.** Each interval is 95% (Wilson).",
        "",
        "**Serving:** the Spark moved from SGLang v0.5.20 to v0.5.22 at 2026-10-26 "
        "14:45Z. The arms' first runs were on v0.5.20 and the screen's on v0.5.22; each "
        "cell below says how many of its runs were on each.",
        "",
        "| Case | Verdict | " + " | ".join(arm or "baseline" for arm in ARMS) + " |",
        "|---|---|" + "---|" * len(ARMS),
    ]
    for case in CASES:
        row = [found[(case, arm)] for arm in ARMS]
        shown = []
        for c in row:
            low, high = wilson(c.passes, c.n)
            shown.append(f"{c.passes}/{c.n} ({low:.0%}–{high:.0%}) {c.state()}")
        lines.append(f"| {case} | **{verdict(row)}** | " + " | ".join(shown) + " |")
    lines += ["", "**Decisive runs next** (each could change its case's verdict):", ""]
    lines += [f"- {case}, {arm or 'baseline'}" for case, arm in plan(rows)] or ["- none"]
    for case in CASES:
        lines += ["", f"### {case}", ""]
        for arm in ARMS:
            c = found[(case, arm)]
            ends = Counter(
                "pass" if r["fault"] is None else f"{r['fault']} ({r['stop'] or r['ending']})"
                for r in c.runs
            )
            firsts = [
                r["calls_to_first_compile"] for r in c.runs if r.get("calls_to_first_compile")
            ]
            first = (
                f"median {statistics.median(firsts):g}, {min(firsts)}–{max(firsts)}"
                if firsts
                else "none"
            )
            rates: Counter[str] = Counter()
            seen: Counter[str] = Counter()
            first_failures = []
            for r in c.runs:
                found_checks = checks_of(records / case / r["run"])
                if not found_checks:
                    continue
                failing = [x["name"] for x in found_checks if not x["ok"]]
                if failing:
                    first_failures.append(failing[0])
                for x in found_checks:
                    seen[x["name"]] += 1
                    rates[x["name"]] += bool(x["ok"])
            weakest = sorted(seen, key=lambda k: rates[k] / seen[k])[:4]
            rate = ", ".join(f"{k} {rates[k]}/{seen[k]}" for k in weakest if rates[k] < seen[k])
            served = Counter(served_on(r) for r in c.runs)
            lines.append(
                f"- **{arm or 'baseline'}**, {c.passes}/{c.n} "
                f"({', '.join(f'{k} ×{v}' for k, v in sorted(served.items()))}): ended "
                + ", ".join(f"{k} ×{v}" for k, v in ends.items())
                + f"; first compile {first}"
                + (f"; weakest checks {rate}" if rate else "")
                + (
                    f"; first failing {', '.join(sorted(set(first_failures)))}"
                    if first_failures
                    else ""
                )
            )
    return "\n".join(lines)


def measure_capped(rows: list[dict[str, Any]], records: Path) -> int:
    """Measure, in the container, each capped run's last files: offline, no model call.
    Writes `capped_checks.json` beside its records; a run already measured is skipped."""
    import contextlib  # noqa: PLC0415
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from cad_eval import container  # noqa: PLC0415
    from cad_eval.cases import CASES as ALL  # noqa: PLC0415
    from cad_eval.run import judge, requests  # noqa: PLC0415
    from cad_eval.tools import PartTools  # noqa: PLC0415

    done = 0
    for cell in cells(rows).values():
        for r in cell.runs:
            record = records / cell.case / r["run"]
            if r.get("stop") != "call_cap" or (record / "capped_checks.json").exists():
                continue
            case = ALL[cell.case]
            with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
                work = Path(tmp) / "case"
                work.mkdir()
                for output in case.outputs():
                    if (record / "files" / output).exists():
                        shutil.copy(record / "files" / output, work / output)
                held = container.held(work, f"spread-{os.getpid()}-{done}")
                if not held.start().ok:
                    continue
                try:
                    tools = PartTools(work, held, case.outputs())
                    measured = {
                        m.name: (
                            tools.measure_request(request)
                            if (work / request["path"]).exists()
                            else {"path": request["path"], "error": "not written by the cap"}
                        )
                        for m in case.members
                        for request in [requests(case)[m.name]]
                    }
                    _, found = judge(case, {"code": 0, "measured": measured})
                finally:
                    held.stop()
            note = "the run hit the call cap: its last files, measured afterwards"
            (record / "capped_checks.json").write_text(
                json.dumps({"note": note, "checks": found}, indent=1), encoding="utf-8"
            )
            done += 1
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad_eval.spread", description=__doc__.split("\n\n")[0])
    parser.add_argument("--measure-capped", action="store_true", help="measure capped runs first")
    parser.add_argument("--next", action="store_true", help="the decisive runs, one per line")
    parser.add_argument("--gap-by-pass", action="store_true", help="a pass rules out a gap")
    args = parser.parse_args(argv)
    from common.config import load  # noqa: PLC0415

    records = load().records_dir / "cad_eval"
    rows = [json.loads(line) for line in (RESULTS / "cad_eval.jsonl").read_text().splitlines()]
    if args.next:
        for case, arm in plan(rows, args.gap_by_pass):
            print(case, arm or "baseline")
        return 0
    if args.measure_capped:
        print(f"measured {measure_capped(rows, records)} capped runs' last files")
    print(report(rows, records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
