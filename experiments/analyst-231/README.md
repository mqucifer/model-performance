# Does a focused context let the Business Analyst split an epic from less?

**From:** mqucifer/crew#231 (focused context), before infra had Goals.
**Ran:** 2026-09-30, read-only, through LiteLLM on the Spark.
**Status:** concluded. A worked example; see [worked-examples.md](../worked-examples.md).
**Harness:** in mqucifer/crew, [`experiments/analyst-231/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/analyst-231) at 39e9865.

## The question

Refinement handed the Business Analyst the whole repository for every epic,
which put every split over 60k tokens, where empty answers begin
(mqucifer/crew#312). With a map of the repository, the files the epic names,
and up to two asks for more, does it still split the epic well, and from how
much less?

## Method

- **The case:** mqucifer/sprint-metrics#62, split by the crew's own `split_epic`
  with the context refinement now builds (`focused_context`).
- **Measures:** the repository part's size in characters, before and after;
  how many stories and asks; time.
- **Also measured, without a model call:** the same context's size for the
  other epics, at refinement's 60k-character threshold.

## What it reads

The project record and a fresh clone of sprint-metrics. Nothing from the crew's
record.

## Harness

| File | Does |
|---|---|
| [`run.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/analyst-231/run.py) | Clones sprint-metrics to a temporary folder, builds the focused context, runs `split_epic` with the ask limit, and writes the result |

## How to run it

1. **Before:** the crew is idle; LiteLLM and the model are up.
2. **Run,** from the crew checkout's root:
   `uv run python experiments/analyst-231/run.py`
3. **Results:** `result.json` beside the harness. Under infra's rules, it'd go
   to `$INFRA_RESULTS/analyst-231/<run-id>/`.

## What it changes

Nothing. A temporary clone, nothing posted.
