# Does a UX Designer's note give each story testable criteria for what a reader sees?

**From:** mqucifer/crew#377 (the UX Designer role), its "done when", before infra had Goals.
**Ran:** 2026-09-30, read-only, through LiteLLM on the Spark.
**Status:** concluded. A worked example; see [worked-examples.md](../worked-examples.md).
**Harness:** in mqucifer/crew, [`experiments/ux-377/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/ux-377) at 39e9865.

## The question

When the UX Designer writes its presentation note against an epic's stories,
does every story get criteria about what a reader sees that a test can check?

## Method

- **The case:** mqucifer/sprint-metrics#62, not yet split. The Business Analyst
  splits it first, in memory; then the UX Designer writes its note against
  those stories.
- **Nothing is posted:** the stories get stand-in numbers (9001 to 9004).
- **Measures:** stories and criteria; coverage problems; anything beyond reach;
  whether each criterion can be checked in the output; time per role.

## What it reads

The project record, the epic from GitHub, and a fresh clone of sprint-metrics.
Nothing from the crew's record.

## Harness

| File | Does |
|---|---|
| [`run.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/ux-377/run.py) | Clones sprint-metrics, splits the epic with `split_epic`, writes the note with `write_note`, checks coverage, and writes the stories and note |

## How to run it

1. **Before:** the crew is idle; LiteLLM and the model are up.
2. **Run,** from the crew checkout's root:
   `uv run python experiments/ux-377/run.py`
3. **Results:** `results/` beside the harness. Under infra's rules, they'd go to
   `$INFRA_RESULTS/ux-377/<run-id>/`.

## What it changes

Nothing. A temporary clone, stand-in numbers, nothing posted.
