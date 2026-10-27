"""Run parts of the CAD-code evaluation on a model (mqucifer/model-performance#3).

    uv run cad-eval spacer l-bracket
    uv run cad-eval --first          # one part per tier: the first run
    uv run cad-eval --all --model crew-candidate --cap 40
    uv run cad-eval --hard-first     # the harder cases' first five (mqucifer/model-performance#16)
    uv run cad-eval --hard           # every harder case, at a time the operator gives

Each part gets a fresh directory and its own container from the CadQuery image, held
by crew's sandbox, and a session with the Developer's model through LiteLLM on :4000
with the builders' key. At `done` its script is run again from a clean start and what
it writes is checked: it compiles, its mesh is closed, its dimensions are within
tolerance. A harder case (`cad_eval/cases.py`) writes a STEP file per member, each
checked by its own measures, and its row says whose a failure is (`fault`).

The run's records (its events, the files it wrote, its checks and result) go to the
records directory on the Mac; its numbers go to `results/cad_eval.jsonl`. Every ending
is handled: a run that can't start is `refused` with why, in a word, and the container
and directory are removed whatever happens.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cad_eval import cases, checks, container, identity, skills
from cad_eval.cases import CASES, Case
from cad_eval.parts import FIRST, PARTS, Part, UnknownPart, part
from cad_eval.send import StreamingSender
from cad_eval.session import BACKSTOP_S, SYSTEM, Session, system_for
from cad_eval.tools import ARMS, PartTools
from common import crew, records, results, spend
from common.config import Settings, load
from common.litellm import Sender, builders_key

SUITE = "cad_eval"
# Cases run at once append their rows to one file.
RESULTS_LOCK = threading.Lock()
# A part's calls (the operator, 2026-10-25): 20 ended two of the first run's five, so it
# starts high and comes down from each part's `calls_to_done`.
CAP_PER_PART = 40
# The base arm's (#40, A6): high, so a run tells what a lower cap would have done; it's
# lowered from the calls each run took to its first clean run. The model isn't told it.
CAP_BASE = 50


class Refused(Exception):
    def __init__(self, why: str, detail: str) -> None:
        super().__init__(f"{why}: {detail}")
        self.why = why
        self.detail = detail


def lookup(name: str) -> Part | Case:
    """A part of the 30, or a harder case."""
    if name in CASES:
        return CASES[name]
    try:
        return part(name)
    except UnknownPart:
        raise UnknownPart(
            f"no part or case {name!r}; the parts are {', '.join(PARTS)}; "
            f"the cases are {', '.join(CASES)}"
        ) from None


def requests(case: Case) -> dict[str, dict[str, Any]]:
    """Each member's measure: its probes, and only the measures its checks need."""
    members = {m.name for m in case.members}
    found = {}
    for m in case.members:
        request: dict[str, Any] = {"path": f"{m.name}.step", "probes": m.probes(), "print": True}
        if m.gaps:
            request["against"] = [
                {"name": g.other, "path": f"{g.other}.step"}
                if g.other in members
                else {"name": g.other, "source": case.mates[g.other]}
                for g in m.gaps
            ]
        if m.own_gap is not None:
            request["self"] = True
        if m.holes:
            request["cylinders"] = True
        if m.load is not None:
            request["section"] = {"axis": m.load.axis, "at": m.load.at}
        if m.vents is not None:
            request["rays"] = {"axis": m.vents.axis, "points": m.vents.points()}
        found[m.name] = request
    return found


# Whose a failure is, in a word: the model's (a wrong design, or no design), a tool's
# (the evaluation's own tools failed it), the infrastructure's (the container, the
# proxy, the model's server: nothing about the case), or the budget's (the call cap
# or a backstop ended it before an answer: no verdict on the design).
INFRA_STOPS = {"call_failed", "workspace_gone", "no_image", "container_start"}
TOOL_ERRORS = ("the measure didn't finish", "it loads but can't be measured")


def fault(row: dict[str, Any], measured: dict[str, Any], troubles: dict[str, int]) -> str | None:
    """Whose the failure is, or None for a case that passed every check.

    A `blocked` the model said is counted the model's here; its reason, in the
    records, is read by hand in the write-up, since a missing tool may be what it
    says (`cad_eval/README.md`).
    """
    if row["ending"] == "crashed":
        return "tool"
    if row["ending"] == "refused" or row["stop"] in INFRA_STOPS:
        return "infra"
    if row["stop"] in ("call_cap", "backstop", "context_full"):
        return "budget"
    if row["ending"] == "done":
        errors = [str(m.get("error", "")) for m in measured.values()]
        if any(e.startswith(TOOL_ERRORS) for e in errors):
            return "tool"
        if row["compiles"] and row["closed_mesh"] and row["within_tolerance"]:
            return None
        return "model"
    return "tool" if troubles else "model"


def judge(case: Case, final: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A case's row fields from its final run, and its named checks for `checks.json`."""
    measured = final["measured"]
    found: list[dict[str, Any]] = []
    passed = 0
    load_ok = None
    # Overhangs and bridges, recorded for the members that passed: never a check
    # (the Sponsor, 2026-10-25: printability is a second pass on a part's files).
    printing: list[dict[str, Any]] = []
    for m in case.members:
        own = checks.member(m, measured[m.name])
        passed += all(c.ok for c in own)
        if all(c.ok for c in own) and measured[m.name].get("print"):
            printing.append(measured[m.name]["print"])
        for c in own:
            found.append({**asdict(c), "member": m.name})
            if c.name.startswith("load."):
                load_ok = c.ok if load_ok is None else load_ok and c.ok
    ran = final["code"] == 0
    row = {
        "compiles": ran and all(checks.valid(measured[m.name]) for m in case.members),
        "closed_mesh": all(checks.closed(measured[m.name]) for m in case.members),
        "within_tolerance": all(c["ok"] for c in found),
        "checks_passed": sum(c["ok"] for c in found),
        "checks_total": len(found),
        "parts_fit": passed,
        "load_ok": load_ok,
        "overhang_mm2": round(sum(p["overhang_mm2"] for p in printing), 1) if printing else None,
        "bridges": sum(p["bridges"] for p in printing) if printing else None,
        "longest_bridge_mm": max(p["longest_bridge_mm"] for p in printing) if printing else None,
    }
    return row, found


def directory(settings: Settings, p: Part | Case, run: str) -> Path:
    path = settings.work_dir / SUITE / f"{p.name}-{run}"
    path.mkdir(parents=True)
    return path


def keep(source: Path, out: Path) -> None:
    """The files the session left, into its records: they're the model's answers."""
    for found in source.rglob("*"):
        relative = found.relative_to(source)
        if found.is_file() and relative.parts[0] != ".crew-home":
            target = out / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found, target)


def own_calls(events: Path) -> set[str]:
    """The run's own request ids: each `call` event's `response_id`, as the proxy logs it."""
    ids: set[str] = set()
    if not events.exists():
        return ids
    with events.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("kind") == "call" and event.get("response_id"):
                ids.add(str(event["response_id"]))
    return ids


def fresh_run(settings: Settings, name: str) -> tuple[str, Path]:
    """A run id and its new records directory: the shared `records.new_run`, which gives
    two runs of a case that start in the same second each their own suffixed id."""
    return records.new_run(settings, SUITE, name)


def evaluate(
    p: Part | Case,
    settings: Settings,
    send: Sender,
    alias: str,
    *,
    max_tokens: int = 65536,
    workspace_for: Callable[[Path, str], Any] = container.held,
    image_id: Callable[[], str | None] = container.image_id,
    results_dir: Path = results.RESULTS,
    read_spend: Callable[[str], str] | None = None,
    arm: str | None = None,
    concurrency: int = 1,
    sample: int | None = None,
    serving_record: Callable[[], dict[str, Any]] = identity.serving,
    batch_serving: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One part end to end: its row, written to the results once the run has ended.

    `batch_serving` is infra's record of production's serving as the batch started;
    it's read again as the run ends, and a difference is flagged.
    """
    started_at = datetime.now(UTC)
    run, out = fresh_run(settings, p.name)
    harness = identity.harness()
    serving_start = batch_serving if batch_serving is not None else serving_record()
    row: dict[str, Any] = {
        "case": p.name,
        "tier": p.tier,
        "run": run,
        "at": started_at.isoformat(timespec="seconds"),
        "crew_commit": crew.commit(),
        # This checkout and what the session read (`identity.py`, #40 V4).
        "harness_commit": harness["commit"],
        "harness_dirty": harness["dirty"],
        "skills_sha": identity.texts_sha(skills.files(skills.SETS)),
        "model_alias": alias,
        "image": container.IMAGE_V2 if arm == "base" else container.IMAGE,
        "image_id": None,
        "cadquery_version": None,
        "ocp_version": None,
        **serving_start,
        # The serving's image tag, as infra records it: read, never typed.
        "serving": serving_start.get("serving_image"),
        "serving_record_changed": None,
        "served_model": None,
        "served_models": None,
        "served_changed": None,
        "ending": None,
        "stop": None,
        "compiles": None,
        "closed_mesh": None,
        "within_tolerance": None,
        "checks_passed": None,
        "checks_total": None,
        "calls_to_done": None,
    }
    case = p if isinstance(p, Case) else None
    if case is not None:
        row.update(kind=case.kind, parts_total=len(case.members), parts_fit=None)
        row.update(load_ok=None, fault=None)
        row.update(overhang_mm2=None, bridges=None, longest_bridge_mm=None)
        # The arm (null for the baseline), the cases run at once, and the first compile.
        row.update(arm=arm, concurrency=concurrency, calls_to_first_compile=None)
        # Which of a `--repeat` run's samples this is (mqucifer/model-performance#27).
        row["sample"] = sample
        row.update(runaways=None, runaway_reasoning_tokens=None, runaway_content_tokens=None)
        row.update(views=None, image_tokens=None, plans=None, plan_passed=None, compactions=None)
        row["plan_misses"] = None
    kept: dict[str, Any] = {}
    send.ticking()
    began = time.monotonic()
    root: Path | None = None
    workspace: Any = None
    tools: PartTools | None = None
    session: Session | None = None
    try:
        image = row["image"]
        # The base arm's image is the v2 image (#40): the same CadQuery, plus OSMesa.
        row["image_id"] = image_id() if image_id is not container.image_id else image_id(image)
        if row["image_id"] is None:
            raise Refused("no_image", f"{image} isn't built: cad_eval/image/build.sh")
        root = directory(settings, p, run)
        if workspace_for is container.held:
            workspace = container.held(root, f"cad-{p.name}-{run}", image=image)
        else:
            workspace = workspace_for(root, f"cad-{p.name}-{run}")
        started = workspace.start()
        if not started.ok:
            raise Refused("container_start", started.output[-3000:])
        tools = PartTools(root, workspace, case.outputs() if case else None, arm=arm, spec=p.spec())
        found = tools.versions()
        row["cadquery_version"], row["ocp_version"] = found["cadquery"], found["ocp"]
        session = Session(
            p.spec(),
            tools,
            send,
            alias,
            out / "events.jsonl",
            max_tokens=max_tokens,
            system=system_for(case.outputs(), base=arm == "base") if case else SYSTEM,
            start=skills.start_line(skills.for_arm(arm)) if arm else "",
            # A harder case is capped by its calls alone, never by time, so its result
            # doesn't depend on the Spark's load (the operator, 2026-10-25): under
            # load an hour of model time is a handful of calls.
            backstop_s=math.inf if case else BACKSTOP_S,
        )
        session.keep_reasoning = arm == "base"
        ending = session.run()
        row["ending"], row["stop"] = ending.how, ending.stop or None
        row["calls_to_done"] = session.calls if ending.how == "done" else None
        if case is not None:
            row["calls_to_first_compile"] = session.first_compile
            row["runaways"] = len(session.runaways)
            row["views"] = session.views
            row["compactions"] = session.compactions if arm == "base" else None
            row["image_tokens"] = session.usage.get("image_tokens", 0)
            if tools.planned:
                row["plans"], row["plan_passed"] = tools.plans, tools.plan_passed
                row["plan_misses"] = tools.plan_misses
            if session.runaways:
                row["runaway_reasoning_tokens"] = sum(r["reasoning"] for r in session.runaways)
                row["runaway_content_tokens"] = sum(r["content"] for r in session.runaways)
        kept["said"] = ending.said
        if ending.how == "done" and case is not None:
            final = tools.final_case(str(ending.said["script"]), requests(case))
            judged, found_checks = judge(case, final)
            row.update(judged)
            final["checks"] = found_checks
            (out / "checks.json").write_text(json.dumps(final, indent=1), encoding="utf-8")
            kept["measured"] = final["measured"]
        elif ending.how == "done":
            final = tools.final(str(ending.said["script"]), p.probes(), p.mate)
            measured = final["measured"]
            found = checks.dimensions(p, measured)
            row["compiles"] = final["code"] == 0 and checks.valid(measured)
            row["closed_mesh"] = checks.closed(measured)
            row["within_tolerance"] = all(c.ok for c in found)
            row["checks_passed"] = sum(c.ok for c in found)
            row["checks_total"] = len(found)
            final["checks"] = [asdict(c) for c in found]
            (out / "checks.json").write_text(json.dumps(final, indent=1), encoding="utf-8")
    except Refused as refused:
        row["ending"], row["stop"] = "refused", refused.why
        kept["refused"] = refused.detail
    except Exception as exc:  # noqa: BLE001 - a crash still ends the run with a row
        row["ending"], row["stop"] = "crashed", type(exc).__name__
        kept["crashed"] = f"{type(exc).__name__}: {exc}"
    finally:
        if workspace is not None:
            workspace.stop()
        if root is not None:
            keep(root, out)
            shutil.rmtree(root, ignore_errors=True)
        row.update(counts(session))
        served = list(dict.fromkeys(session.served)) if session else []
        kept["served"] = served
        row["served_model"] = served[0] if served else None
        row["served_models"] = len(served)
        row["served_changed"] = len(served) > 1
        serving_end = serving_record()
        kept["serving_end"] = serving_end
        row["serving_record_changed"] = any(
            serving_end.get(k) != v for k, v in serving_start.items()
        )
        # Every other call through the proxy while this one ran (`common/spend.py`).
        overlapped = spend.others(
            started_at, datetime.now(UTC), own_calls(out / "events.jsonl"), read_spend
        )
        row["other_calls"] = None if overlapped is None else sum(overlapped.values())
        row["other_aliases"] = spend.keys(overlapped) if overlapped else None
        if case is not None:
            troubles = tools.troubles if tools is not None else {}
            row["fault"] = fault(row, kept.pop("measured", {}), troubles)
        row["wall_s"] = round(time.monotonic() - began, 1)
        send.ticking()
        row["concurrent_tick"] = send.tick_seen
        row["tick_calls"] = send.tick_calls
        (out / "result.json").write_text(
            json.dumps({**row, **kept}, indent=1, default=str), encoding="utf-8"
        )
    with RESULTS_LOCK:
        results.append(SUITE, row, results_dir)
    return row


def counts(session: Session | None) -> dict[str, Any]:
    """The session's numbers, zero for one that never started."""
    outcomes = session.outcomes if session else {}
    by_tool = session.by_tool if session else {}
    usage = session.usage if session else {}
    total = sum(outcomes.values())
    return {
        "calls": session.calls if session else 0,
        "model_s": round(session.model_s, 1) if session else 0.0,
        "tool_calls": total,
        "malformed_tool_calls": outcomes.get("malformed", 0),
        "ill_typed_tool_calls": outcomes.get("ill_typed", 0),
        "failed_tool_calls": outcomes.get("failed", 0),
        "reliable_tool_calls": outcomes.get("ok", 0),
        "tool_reliability": round(outcomes.get("ok", 0) / total, 4) if total else None,
        "writes": by_tool.get("write", 0),
        "runs": by_tool.get("run", 0),
        "inspects": by_tool.get("inspect", 0),
        **{
            k: usage.get(k, 0)
            for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens")
        },
    }


def summary(p: Part | Case, row: dict[str, Any], settings: Settings) -> str:
    return (
        f"{p.name} (tier {p.tier}): {row['ending']}"
        f"{', fault ' + str(row['fault']) if 'fault' in row else ''}"
        f"{' (' + row['stop'] + ')' if row['stop'] else ''}; "
        f"compiles {row['compiles']}, closed {row['closed_mesh']}, "
        f"within {row['within_tolerance']} "
        f"({row['checks_passed']}/{row['checks_total']}); "
        f"{row['calls']} calls, {row['tool_calls']} tool calls, "
        f"reliability {row['tool_reliability']} "
        f"({row['malformed_tool_calls']} malformed, {row['ill_typed_tool_calls']} "
        f"ill-typed, {row['failed_tool_calls']} failed); {row['model_s']} model s; "
        f"records {settings.records_dir / SUITE / p.name / row['run']}"
    )


# Memory kept free for everything else Docker runs (LiteLLM, its database, the crew's
# own containers) when deciding how many of the sandbox's containers fit at once.
RESERVE = 1024**3
UNITS = {
    **{"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4},
    **{"KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4},
}
# A file in the work directory that stops a run from starting more cases: the ones
# running finish (the operator's, when another builder needs the Spark to itself).
STOP_FILE = "cad_eval.stop"


def size(text: str) -> float:
    """Bytes in one of `docker stats`'s sizes, such as `1.162GiB`."""
    found = re.fullmatch(r"([\d.]+)\s*([kKMGT]?i?B)", text.strip())
    if not found:
        return 0.0
    return float(found.group(1)) * UNITS.get(found.group(2).replace("k", "K"), 1)


def sandbox_memory() -> float:
    """The memory the crew's sandbox gives each container, from its own argv."""
    from crew_org.tools.sandbox import Sandbox  # noqa: PLC0415

    argv = Sandbox(image=container.IMAGE).command(Path("/work"), ["true"], network=False)
    given = argv[argv.index("--memory") + 1]
    return size(given.upper().replace("G", "GiB").replace("M", "MiB"))


def parallel_room(run: Callable[..., Any] = subprocess.run) -> int:
    """How many of the sandbox's containers Docker's free memory holds now: its total
    less what its containers use and a reserve, over each container's memory cap."""
    try:
        total = run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        used = run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return 0
    if not total.isdigit():
        return 0
    taken = sum(size(line.split("/")[0]) for line in used)
    return max(0, int((int(total) - taken - RESERVE) // sandbox_memory()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad-eval", description=__doc__.split("\n\n")[0])
    parser.add_argument("parts", nargs="*", help=f"one or more of: {', '.join([*PARTS, *CASES])}")
    chosen_by = parser.add_mutually_exclusive_group()
    chosen_by.add_argument("--first", action="store_true", help="one part per tier")
    chosen_by.add_argument("--all", action="store_true", help="every part, one at a time")
    chosen_by.add_argument("--hard", action="store_true", help="every harder case")
    chosen_by.add_argument("--hard-first", action="store_true", help="the harder cases' first five")
    parser.add_argument("--model", help="a LiteLLM alias in place of the Developer's")
    parser.add_argument(
        "--arm", choices=ARMS, help="what the session is given besides the baseline's tools"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="samples of each harder case, each its own run and row (`sample`)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="harder cases run at once: at most what the operator gives, and Docker's memory holds",
    )
    parser.add_argument(
        "--cap",
        type=int,
        help=f"calls a part may make (default {CAP_PER_PART}, or {CAP_BASE} in the base arm)",
    )
    parser.add_argument(
        "--total", type=int, help="calls the whole run may make (default: the cap for each part)"
    )
    args = parser.parse_args(argv)
    if args.cap is None:
        args.cap = CAP_BASE if args.arm == "base" else CAP_PER_PART
    if bool(args.parts) == (args.first or args.all or args.hard or args.hard_first):
        parser.error("name the parts, or --first, --all, --hard or --hard-first")
    harness = identity.harness()
    if harness["dirty"]:
        # A row names the harness commit it ran: refused, so that commit is the code.
        print("refused: the harness has uncommitted changes: commit them first", file=sys.stderr)
        return 2
    try:
        names = (
            list(PARTS)
            if args.all
            else list(FIRST)
            if args.first
            else list(CASES)
            if args.hard
            else list(cases.FIRST)
            if args.hard_first
            else args.parts
        )
        chosen = [lookup(n) for n in names]
    except UnknownPart as exc:
        parser.error(str(exc.args[0]))
    if args.repeat < 1 or (args.repeat > 1 and not all(isinstance(p, Case) for p in chosen)):
        parser.error("--repeat is a whole number of samples of the harder cases")
    runs = [(p, k + 1 if args.repeat > 1 else None) for p in chosen for k in range(args.repeat)]
    total = args.total if args.total is not None else args.cap * len(runs)
    if args.parallel > 1 and not all(isinstance(p, Case) for p in chosen):
        parser.error("--parallel runs the harder cases only: the 30 parts' runs stay one at a time")

    from crew_org.calls import role_spec  # noqa: PLC0415

    from swap.runners import ticks_running  # noqa: PLC0415

    if ticks_running():
        # The harder cases test correctness, capped by calls, so they share the Spark
        # with a tick, each row recording it (`concurrent_tick`, `other_calls`): the
        # operator, 2026-10-25. The 30 parts' runs, which compare times, still wait.
        if not all(isinstance(p, Case) for p in chosen):
            print("refused: a crew tick is running, and it shares the model", file=sys.stderr)
            return 2
        print("a crew tick is running: each row records it", file=sys.stderr, flush=True)
    if container.image_id() is None:
        print(f"refused: {container.IMAGE} isn't built: cad_eval/image/build.sh", file=sys.stderr)
        return 2
    settings = load()
    spec = role_spec("developer")
    alias = args.model or str(spec.get("llm"))
    params = spec.get("llm_params") or {}
    timeout = float(params.get("timeout", 3600))
    max_tokens = int(params.get("max_tokens", 65536))
    try:
        key = builders_key(settings)
    except (LookupError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    preflight = Sender(settings, key, cap=0)
    try:
        if not preflight.lists(alias):
            print(f"refused: LiteLLM doesn't list {alias} for the builders' key", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - any failure to reach the proxy refuses the run
        print(f"refused: LiteLLM on :4000 didn't answer ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        preflight.close()

    room = parallel_room()
    if args.parallel > room:
        print(
            f"refused: --parallel {args.parallel}, but Docker's free memory holds {room} "
            "of the sandbox's containers",
            file=sys.stderr,
        )
        return 2

    # What production serves as the batch starts, from infra's record (`identity.py`).
    batch_serving = identity.serving()
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    stop = settings.work_dir / STOP_FILE
    stop.unlink(missing_ok=True)
    budget = {"reserved": 0, "failed": 0}
    lock = threading.Lock()

    def one(p: Part | Case, sample: int | None) -> None:
        with lock:
            if stop.exists():
                print(f"{p.name}: not started, {stop} says stop", flush=True)
                return
            cap = min(args.cap, total - budget["reserved"])
            if cap < 1:
                print(f"{p.name}: not run, the run's {total} calls are spent", flush=True)
                return
            budget["reserved"] += cap
        # A harder case's calls are streamed (`cad_eval/send.py`); the 30 parts' stay whole.
        sending = StreamingSender if isinstance(p, Case) else Sender
        send = sending(settings, key, cap=cap, alias=args.model, timeout=timeout)
        try:
            row = evaluate(
                p,
                settings,
                send,
                alias,
                max_tokens=max_tokens,
                arm=args.arm,
                concurrency=args.parallel,
                sample=sample,
                batch_serving=batch_serving,
            )
        finally:
            with lock:
                budget["reserved"] -= cap - send.calls
            send.close()
        with lock:
            budget["failed"] += row["ending"] in ("refused", "crashed")
            print(summary(p, row, settings), flush=True)

    # The crew's sandbox keeps its uv cache under the current directory: the work's.
    with contextlib.chdir(settings.work_dir), ThreadPoolExecutor(args.parallel) as pool:
        for done in [pool.submit(one, p, sample) for p, sample in runs]:
            done.result()
    failed = budget["failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
