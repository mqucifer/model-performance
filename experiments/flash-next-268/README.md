# Does another model answer the request the 27B leaves empty?

**From:** mqucifer/crew#422 and mqucifer/crew#312 (empty answers), before infra had Goals.
**Ran:** 2026-09-30 to 2026-10-01.
**Status:** findings written. A worked example; see [worked-examples.md](../worked-examples.md).
**Harness:** in mqucifer/crew, [`experiments/flash-next-268/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/flash-next-268) and [`scripts/replay_request.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/scripts/replay_request.py), at 39e9865.

## The question

On the crew's hardest known request, production's 27B answers empty four times
in five. Does Qwen3.8-Flash-Next answer it, and are its answers ones the crew
could use?

## Method

- **The case:** one stored request, the Developer's for
  mqucifer/sprint-metrics#268: 115,867 prompt tokens, JSON schema `FirstOrDone`.
- **Arms,** each replaying that request through the proxy:

  | Arm | Model and server |
  |---|---|
  | `27b-production-low` | Qwen3.8-27B NVFP4, SGLang v0.5.20, DFlash2, 8-bit KV, effort `low` |
  | `27b-medium-effort` | the same at `medium` |
  | `27b-kv-bf16` | the same with a 16-bit KV cache |
  | `27b-fp8-weights` | Qwen's 8-bit weights |
  | `flash-next-*` | Qwen3.8-Flash-Next on TensorFold, default seed and seeds 1 to 5 |

- **Measures:** how each run finished, its tokens, and whether its answer is
  usable, judged as the crew's parser would.
- **Server changes** (another model, a KV setting) are made at launch on the
  Spark by the Sponsor, and production is put back afterwards.

## What it reads

- **LiteLLM's spend log,** where the proxy keeps every response: the answers,
  read by alias and start time. The answers stay there; they're content.
- **The stored request,** exported from the spend log as the empty-answers
  runbook describes.

## Harness

| File | Does |
|---|---|
| [`scripts/replay_request.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/scripts/replay_request.py) | Replays a stored request through the proxy, N times, and records what came back. An arm ending in `miss` forces a prefix-cache miss; `--seed` sends each run its number |
| [`check_answers.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/flash-next-268/check_answers.py) | Reads an alias's answers from the spend log since a time, strips a JSON fence, and validates each against the Developer's `FirstOrDone` |

## How to run it

1. **Before:**
   - The crew is idle.
   - Export the request (see
     [runbooks/empty-model-answers.md](../../runbooks/empty-model-answers.md),
     "Reproducing it").
   - For a model other than production's, the Sponsor stops the 27B, starts
     the other on the Spark, and enables its alias in LiteLLM. It takes the
     whole Spark and its serving port.
2. **Run,** from the crew checkout's root:
   ```
   uv run python scripts/replay_request.py <request.json> <arm> 5 --seed
   uv run python experiments/flash-next-268/check_answers.py crew-flash-next <since UTC>
   ```
3. **Results:** one row per run beside the request. Under infra's rules, they'd
   go to `$INFRA_RESULTS/flash-next-268/<run-id>/`. The answers stay in the
   spend log.
4. **After:** the Sponsor restarts production's 27B and comments the alias out
   again, before any tick.

## What it changes

Nothing by the harness. The model swap is the Sponsor's, and is put back.
