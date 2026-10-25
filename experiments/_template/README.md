# <The question, in a line>

**Goal:** mqucifer/infra#<n>. **Story:** mqucifer/infra#<n>. **Status:** designed | running | findings written | concluded

## The question

One question, as the Goal puts it. What would change if we knew the answer?

## Method

- **Arms:** what varies between them, and what stays fixed.
- **Cases:** which requests, cards or runs, chosen how, and how many.
- **Runs:** how many per arm, and why that many.
- **Measures:** what is read, from where, and how it's computed.
- **Decision rule,** agreed before anything runs: what result would mean what.

## What it reads

- **The crew's record:** which events and fields, by id.
- **Metrics, logs and traces:** which, from where. Grafana keeps 7 days; older
  history is local.
- **LiteLLM and SGLang:** what, and how a call is matched to them.

## Harness

| File | Does |
|---|---|
| `run.py` | ... |
| `analyse.py` | ... |

## How to run it

1. **Before:** the crew is idle (`pgrep -f "crew tick"` finds nothing); the
   stack is healthy (`runbooks/`); any setting the Sponsor must apply first.
2. **Run:** the commands, from which checkout.
3. **Results:** written to `$INFRA_RESULTS/<slug>/<run-id>/`, with `run.json`.
4. **After:** anything the Sponsor puts back.

## What it changes

Nothing, on any machine. A setting an arm needs is listed above for the Sponsor.
