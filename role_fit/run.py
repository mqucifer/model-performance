"""Which model fits each of the crew's roles: E1's calls replayed per role group (#10).

    uv run role-fit select                 # print the cases from the crew's events
    uv run role-fit extract                # copy their requests from LiteLLM's spend log
    uv run role-fit run --runs 3           # replay every case three times
    uv run role-fit run dev-first --model crew-candidate

Each case is one request production sent, replayed as it was sent (the alias in
place of production's with `--model`), with its own seed per run, streamed and
cut off on a runaway as crew's call layer does. Its answer is scored in its own
form (`score.py`), beside production's outcome for the same request, so a
difference is the model's, not the prompt's.

The answer and its thinking go to the records directory on the Mac; the numbers go
to `results/role_fit.jsonl`. Runs go case by case within each round, so a stopped
run still covers the cases evenly. Every ending leaves a row: `refused` (the
request isn't extracted), `interrupted` (the call failed or the cap was reached),
or `crashed`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import crew, records, results
from common.config import Settings, load
from common.litellm import CallCapReached, Sender, builders_key
from role_fit import extract, score, select
from role_fit.cases import Case, UnknownCase, chosen
from role_fit.send import StreamingSender

SUITE = "role_fit"


def production(request: dict[str, Any], schema: str, response: Any) -> dict[str, Any]:
    """Production's own answer to the request, scored as the replay's is: like for like."""
    try:
        choice = response["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        return {"prod_form_valid": None, "prod_hedges_per_10k": None}
    text = str(message.get("content") or "")
    return {
        "prod_form_valid": score.score(request, schema, text, choice.get("finish_reason"))["valid"],
        "prod_hedges_per_10k": score.hedges_per_10k(str(message.get("reasoning_content") or "")),
    }


def replay(
    c: Case,
    settings: Settings,
    send: Sender,
    *,
    seed: int,
    results_dir: Path = results.RESULTS,
) -> dict[str, Any]:
    """One case, once: its row, written to the results once the call has ended."""
    run = f"{records.run_id()}-s{seed}"
    out = records.run_dir(settings, SUITE, c.id, run)
    row: dict[str, Any] = {
        "case": c.id,
        "run": run,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "crew_commit": crew.commit(),
        "model_alias": None,
        "ending": None,
        "stop": None,
        "bucket": c.bucket,
        "group": c.group,
        "role": c.role,
        "card": c.card,
        "schema": c.schema,
        "seed": seed,
        "valid": None,
        "why": None,
        "calls": 0,
        "tool_calls": 0,
        "malformed_tool_calls": 0,
        **{
            f"prod_{k}": getattr(c, f"prod_{k}")
            for k in (
                "valid",
                "empty",
                "finish",
                "prompt_tokens",
                "completion_tokens",
                "reasoning_tokens",
                "duration_s",
            )
        },
    }
    kept: dict[str, Any] = {}
    send.ticking()
    began = time.monotonic()
    try:
        try:
            given = extract.load(settings, c)
        except extract.NotFound as exc:
            row["ending"], row["stop"] = "refused", "no_request"
            kept["refused"] = str(exc)
            return row
        request = given["request"]
        row["model_alias"] = send.alias or request.get("model")
        row["form"] = score.form(request)
        row["dated"] = score.dated(request, c.schema)
        row.update(production(request, c.schema, given.get("production")))
        started = time.monotonic()
        try:
            data = send({**request, "seed": seed})
        except CallCapReached as exc:
            row["ending"], row["stop"] = "interrupted", "call_cap"
            kept["interrupted"] = str(exc)
            return row
        except Exception as exc:  # noqa: BLE001 - a failed call is an ending, with a row
            row["ending"], row["stop"] = "interrupted", "call_failed"
            row["calls"] = 1
            kept["interrupted"] = f"{type(exc).__name__}: {exc}"[:400]
            return row
        row["calls"] = 1
        row["model_s"] = round(time.monotonic() - started, 1)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = str(message.get("content") or "")
        thinking = str(message.get("reasoning_content") or "")
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        row.update(
            {
                "ending": "done",
                "finish_reason": None if finish is None else str(finish),
                **score.score(request, c.schema, text, finish),
                "answer_chars": len(text),
                "thinking_chars": len(thinking),
                "hedges_per_10k": score.hedges_per_10k(thinking),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens"
                ),
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            }
        )
        (out / "answer.json").write_text(
            json.dumps({"id": data.get("id"), "content": text, "reasoning_content": thinking}),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - a crash still ends the run with a row
        row["ending"], row["stop"] = "crashed", type(exc).__name__
        kept["crashed"] = f"{type(exc).__name__}: {exc}"[:400]
    finally:
        row["wall_s"] = round(time.monotonic() - began, 1)
        send.ticking()
        row["concurrent_tick"] = send.tick_seen
        row["tick_calls"] = send.tick_calls
        (out / "result.json").write_text(
            json.dumps({**row, **kept}, indent=1, default=str), encoding="utf-8"
        )
        results.append(SUITE, row, results_dir)
    return row


def line(row: dict[str, Any]) -> str:
    verdict = (
        f"{'valid' if row['valid'] else 'invalid (' + str(row['why']) + ')'}"
        if row["ending"] == "done"
        else f"{row['ending']} ({row['stop']})"
    )
    return (
        f"{row['bucket']} {row['case'][:8]} s{row['seed']}: {verdict}, "
        f"{row.get('model_s', '-')} model s, {row.get('reasoning_tokens', '-')} thinking tokens; "
        f"production {'valid' if row['prod_valid'] else 'refused'} in {row['prod_duration_s']} s"
    )


def run_main(args: argparse.Namespace) -> int:
    settings = load()
    try:
        cases = chosen(args.cases)
    except UnknownCase as exc:
        print(f"refused: {exc.args[0]}", file=sys.stderr)
        return 2
    try:
        key = builders_key(settings)
    except (LookupError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    aliases = {args.model} if args.model else set()
    for c in cases:
        if not args.model:
            try:
                aliases.add(str(extract.load(settings, c)["request"].get("model")))
            except extract.NotFound:
                continue
    preflight = Sender(settings, key, cap=0)
    try:
        missing = sorted(a for a in aliases if not preflight.lists(a))
    except Exception as exc:  # noqa: BLE001 - any failure to reach the proxy refuses the run
        print(f"refused: LiteLLM on :4000 didn't answer ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        preflight.close()
    if missing:
        print(f"refused: LiteLLM doesn't list {', '.join(missing)} for the builders' key")
        return 2
    send = StreamingSender(settings, key, cap=args.cap, alias=args.model)
    failed = 0
    try:
        for seed in range(1, args.runs + 1):
            for c in cases:
                row = replay(c, settings, send, seed=seed)
                failed += row["ending"] != "done"
                print(line(row), flush=True)
                if row["stop"] == "call_cap":
                    return 1
    finally:
        send.close()
    return 1 if failed else 0


def extract_main(args: argparse.Namespace) -> int:
    settings = load()
    try:
        cases = chosen(args.cases)
    except UnknownCase as exc:
        print(f"refused: {exc.args[0]}", file=sys.stderr)
        return 2
    missing = 0
    for c in cases:
        try:
            extract.extract(settings, c)
            print(f"{c.bucket} {c.id}: kept")
        except extract.NotFound as exc:
            missing += 1
            print(f"{c.bucket} {c.id}: {exc}")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="role-fit", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("select", help="print the cases chosen from the crew's events")
    for name in ("extract", "run"):
        p = sub.add_parser(name)
        p.add_argument("cases", nargs="*", help="case ids, buckets or groups (default: all)")
    run = sub.choices["run"]
    run.add_argument("--runs", type=int, default=1, help="rounds over the cases, each its seed")
    run.add_argument("--model", help="a LiteLLM alias in place of each request's own")
    run.add_argument("--cap", type=int, help="calls the run may make (default: config's)")
    args = parser.parse_args(argv)
    if args.command == "select":
        return select.main(load().crew_events)
    if args.command == "extract":
        return extract_main(args)
    return run_main(args)


if __name__ == "__main__":
    sys.exit(main())
