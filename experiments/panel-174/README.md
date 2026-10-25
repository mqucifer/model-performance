# Would a refinement panel have caught what went wrong with a Goal's first epics?

**From:** part 5 of the refinement plan agreed with the Sponsor on 2026-10-01 (mqucifer/crew#440), before infra had Goals.
**Ran:** 2026-10-02, 02:15 to 07:00 UTC; replays on 2026-10-05 and 2026-10-08.
**Status:** concluded. A worked example; see [worked-examples.md](../worked-examples.md).
**Harness:** in mqucifer/crew, [`experiments/panel-174/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174) at 39e9865.

## The question

Before an epic is split, the Architect, UX Designer, QA and DevOps each take a
focused pass at it. Would that panel have caught, before the split, what went
wrong with mqucifer/sprint-metrics#174's first epics? Or would its members miss
the same things together, as identical panels did in [panel-359](../panel-359/)?

## Method

- **The case:** the Goal and its epics as they stood on the morning of
  2026-10-01, before the Goal was revised: mqucifer/sprint-metrics#184,
  mqucifer/sprint-metrics#185 and mqucifer/sprint-metrics#187, with
  mqucifer/sprint-metrics#186 (delivered) as a sibling.
- **One run** is 12 calls: three epics, each read by four roles, each role on
  its own alias from the crew's `agents.yaml`. No call sees another's notes.
- **Every member is shown the same context, collected mechanically:** the
  Goal, the project record as the crew shows it, the epic and its siblings, and
  the Sponsor's recorded decisions, found by a written rule.
- **Arms,** three runs each, 108 calls in all:
  - serial (the baseline);
  - serial without the decisions;
  - parallel, each epic's four roles at once (for timing).
- **Score sheet:** ten findings from the review of those epics. A finding
  counts when a note names the requirement that rules the error out, with its
  source. Also counted: unneeded notes, overlap, who would settle each note,
  and cost.
- **What would change the plan,** written before running: the panel catches
  most only with the decisions; members miss the same findings together; or
  many unneeded notes.
- **Replays** with the crew's own panel code on the same inputs: once
  (2026-10-05), then once more with sprint-metrics' decision log in context
  (2026-10-08, mqucifer/crew#468).

## What it reads

- **GitHub:** the Goal's and epics' bodies as they stood at a cutoff, from
  their edit history; the Sponsor's comments, by the collection rule.
- **The project record** at sprint-metrics `01c0357`.
- **LiteLLM's spend log:** per-call timing for each call's window, the model's
  own time separate from CrewAI's around it.

## Harness

All at crew 39e9865, in [`experiments/panel-174/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174):

| File | Does |
|---|---|
| [`collect_decisions.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174/collect_decisions.py) | Runs first. The rule for the Sponsor's decisions: everything the Sponsor wrote before the cutoff on the Goal's cards, or naming the Goal. Writes what it found, and from where |
| [`run_panel.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174/run_panel.py) | The calls, each member built from its role's spec with the crew's `build_agent`; serial or parallel, with or without the decisions |
| [`replay.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174/replay.py) | The crew's own `run_panel` on the stored inputs; `--with-log` adds the project's decision log |
| [`analyse.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174/analyse.py) | The tables, from the answers and the scores |

Every note was scored by reading it, with a reason per note, kept beside the
answers in the crew's `results/`.

## How to run it

1. **Before:** the crew is idle; LiteLLM and the model are up.
2. **Run,** from the crew checkout's root:
   ```
   uv run python experiments/panel-174/collect_decisions.py
   uv run python experiments/panel-174/run_panel.py serial 3 [--no-decisions]
   uv run python experiments/panel-174/run_panel.py parallel 3
   uv run python experiments/panel-174/replay.py 1 [--with-log]
   uv run python experiments/panel-174/analyse.py
   ```
   `--from N` numbers runs from N, to add runs to an arm. One serial run is
   about 50 minutes.
3. **Results:** appended to `results/` beside the harness. Under infra's rules,
   they'd go to `$INFRA_RESULTS/panel-174/<run-id>/`.
4. **Scoring** is by hand: one line per note, with the finding it names and why.

## What it changes

Nothing. The epics were closed and superseded; nothing was written to GitHub.
