# Does a panel of agents catch more than one, and at what cost on the Spark?

**From:** mqucifer/crew discussion 359 (panels and teams), before infra had Goals.
**Ran:** 2026-09-29, after Sprint 10 closed, with nothing else running.
**Status:** concluded. A worked example; see [worked-examples.md](../worked-examples.md).
**Harness:** in mqucifer/crew, [`experiments/panel-359/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359) at 39e9865.

## The question

When should the crew run several agents on one task, and how should they
differ? Measured on three roles: the deploy review, the Developer and the
Architect. Separately, what do three requests at once cost the Spark? That
second half is the DevOps Engineer's (capacity).

## Method

- **Model:** Qwen3.8-27B under SGLang v0.5.20 on the Spark, through LiteLLM on
  the crew's `crew-code-think` alias.
- **Reviews:** the deploy review of mqucifer/sprint-metrics#269's Dockerfile,
  with its four known findings, given the evidence it had on 2026-09-28.
  - Arms: 5 serial with the image rule shown; 2 parallel panels of 3; 5 serial
    with the rule hidden.
  - Measure: which findings each run raised. "Any 3 of 5" is the union of
    every three-run combination.
- **Developer:** four stories whose first attempt failed and which were later
  done: mqucifer/sprint-metrics#200, mqucifer/sprint-metrics#264,
  mqucifer/sprint-metrics#266 and mqucifer/sprint-metrics#334.
  - Replayed at the commit `main` was on when each first attempt began, three
    at once, through delivery's first-attempt path.
  - Arms: the same prompt ×3; a one-line focus each ("smallest change", "most
    robust", "tests first").
  - Measure: a green sandbox check.
- **Architect:** the design revision mqucifer/sprint-metrics#302, which missed
  `serve.py`'s `127.0.0.1` bind. Replayed at sprint-metrics `446d6ec`.
  - Arms: the same prompt ×3; lenses ×3; one proposal and two critics.
  - Measure: did a proposal name the bind?
- **Cost:** wall time per arm against a single run; KV cache use, running
  requests and generation throughput from SGLang's metrics over each arm's
  window.
- **Decision rule,** from the discussion: a panel of three is worth building
  for the gates if its union reliably catches what single runs miss, and three
  in parallel cost well under three single runs.

## What it reads

- **The crew's event log** (`var/events`): each story's first-attempt time, to
  find its base commit. That was matched by time, before records carried a run id.
- **LiteLLM's spend log:** per-request tokens and cached prompt tokens for each
  arm's window. It has no time to first token for non-streaming calls.
- **SGLang's metrics in Grafana,** over each window:
  - `max_over_time(sglang_token_usage[w])`
  - `max_over_time(sglang_num_running_reqs[w])`
  - `avg_over_time(sglang_gen_throughput[w])`
  - time to first token as the `increase` of `sglang_time_to_first_token_seconds_sum` over `_count`
- **Tempo:** `{resource.service.name="crew" && name=~"panel.*"}`.

## Harness

All at crew 39e9865, in [`experiments/panel-359/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359):

| File | Does |
|---|---|
| [`run_panel.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359/run_panel.py) | The deploy review through the crew's `review_deploy`, serial or parallel; tags each verdict's findings by keyword |
| [`replay_dev.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359/replay_dev.py) | A failed first attempt replayed three times, each in its own worktree, through delivery's guards and the sandbox. It refuses to start without the sandbox |
| [`replay_design.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359/replay_design.py) | Three proposals from the crew's `propose_design`: `same`, `lens` or `critic` |
| [`analyse.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359/analyse.py) | Recall per finding for single runs, three-run unions and the panels; each panel's wall time against the median run |

Its inputs (the PR's diff, the evidence, the earlier verdicts, the record) are
in the crew's `inputs/` beside the harness.

## How to run it

1. **Before:** the crew is idle (`pgrep -f "crew tick"` finds nothing); LiteLLM
   and the model are up (`uv run crew doctor`); the sandbox is available for
   `replay_dev.py`.
2. **Run,** from the crew checkout's root:
   ```
   uv run python experiments/panel-359/run_panel.py serial 5 [--hide-rule]
   uv run python experiments/panel-359/run_panel.py parallel 3
   uv run python experiments/panel-359/analyse.py
   uv run python experiments/panel-359/replay_dev.py <card> 3 [--lens]
   uv run python experiments/panel-359/replay_design.py same|lens|critic
   ```
3. **Results:** appended to `results/` beside the harness in the crew checkout.
   The raw model-call log goes to `var/experiments/panel-359/events.jsonl`,
   which isn't committed because it holds prompt text. Under infra's rules,
   results would go to `$INFRA_RESULTS/panel-359/<run-id>/` instead.
4. **After:** read the cost metrics for each arm's window from Grafana, within
   7 days.

## What it changes

Nothing. Read-only clones and worktrees; nothing posted.
