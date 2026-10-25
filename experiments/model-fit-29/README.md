# Which model fits each of the crew's roles, on the Spark

**Goal:** mqucifer/infra#29. **Status:** the 27B baseline is built (mqucifer/model-performance#10); candidates wait for the planned pause. **Built by:** Claude in a session with the Sponsor, not by the crew: infra isn't onboarded to the crew yet, and when it is, this Goal is not one for the crew to decompose.

## The question

For each kind of role the crew runs, is there a model servable on the Spark that does the crew's real work better than Qwen3.8-27B: more answers valid on the first try, fewer empty or runaway answers, more Developer answers whose tests pass, or the same in less time?

Leaderboards measure interactive coding loops, chat and short tasks. The crew asks for one long structured answer at 35–50k prompt tokens, under a grammar, with no one watching. The only ranking that answers this question is the crew's own calls, replayed. If a candidate wins a role here, that role's LiteLLM alias points at it. If none does, the question is closed with evidence, and stays closed until a candidate passes the intake card below.

## Finding candidates

Search by what the crew needs, not for "the best agentic model": rankings carry the setup they were measured in.

| The crew needs | Search for | Where it shows up |
|---|---|---|
| No thinking until the answer is empty | Thinking budgets, hybrid thinking modes, reasoning-effort control | Model cards, release notes |
| One long correct answer, not a chat loop | Whole-task code correctness and edit-format reliability | Aider's polyglot leaderboard (closest to the crew's shape); SWE-bench Verified, with its setup |
| Holding to a form | Function calling and structured output | BFCL, the Berkeley function-calling leaderboard |
| Working at 35–60k tokens | Long-context reasoning, not only a long window | RULER, LongBench v2 |
| Speed on the Spark | Active parameters, NVFP4 weights, speculative drafts | Hugging Face filtered by `nvfp4`; NVIDIA's DGX Spark playbooks; vLLM and SGLang recipe pages |
| Judgement roles | Reasoning under ambiguity | GPQA; the long-context lists above |
| Running on a GB10 | Measured tokens/s on the Spark | Spark users' write-ups: anecdotal, on the hardware |

**The routine:** a scan by these properties each month, or on request ("scan for model candidates" in a crew session). A model that clears the intake card below goes on the watch list, [`candidates.md`](candidates.md), with the need it might serve. The bake-off runs when the list has a real contender, not on every release.

## Candidate intake

A model is tested only if its model card or serving recipe answers yes to all of these. This is also the filter for reading about models: bring the link and these answers.

| # | Question | Why it rules a model out | Where to look |
|---|---|---|---|
| 1 | **Does SGLang serve it, with a reasoning parser, a tool-call parser and xgrammar grammars?** | The crew's call layer needs all three: thinking kept out of answers, reading tools, and the two-part answer grammar (crew ADR 0026). Ollama or GGUF-only models fail here | The model card's "deployment" section; SGLang's docs and recipes; search "<model> SGLang reasoning-parser tool-call-parser" |
| 2 | **Does it fit the Spark with room to work?** Weights at NVFP4 or FP8 well under 128 GB, leaving room for the context cache at 60k+ tokens across concurrent calls | Weights that fill memory leave no cache, and calls queue or fail | The size of its NVFP4 or FP8 checkpoint; "DGX Spark" in its recipe |
| 3 | **Is its context at least 128k?** | The crew sends up to 60k and asks for up to 30k back | The model card |
| 4 | **Can its thinking be bounded or turned off?** A reasoning-effort setting, a thinking budget, or a non-thinking mode | The crew's main model-side failure is thinking until the answer comes back empty | The chat template's options; "reasoning_effort" or "enable_thinking" in its card |
| 5 | **How many parameters are active per token?** And is there a speculative-decoding draft for the Spark | On the Spark, generation speed follows the active parameters: a dense 27B runs about 27 tokens/s, a 3B-active mixture-of-experts several times faster, with less reasoning per token | The model card's architecture; "DSpark", "EAGLE" or "MTP" drafts |
| 6 | **Is it licensed for commercial use?** | The crew's output is ordinary software | The licence |

**Not reasons to bring one:** a coding-agent ranking measured in an IDE loop, a benchmark answered by a frontier model, or "best for agentic development" without the setup it was measured in.

## Method

- **Arms:** one per candidate, each on its own LiteLLM alias, against `crew-code-think` and `crew-analysis` (Qwen3.8-27B) as they run in production. Each arm uses the serving settings its recipe recommends; the README of a run lists them.
- **Role groups:**
  - *execution:* the Developer's first attempts and repairs, QA's verdict, the criteria check;
  - *judgement:* the Product Owner's decompose and settle, the Architect's pass, the split.
- **Cases:** calls made during crew#583's E1 on Goal mqucifer/sprint-metrics#558 after mqucifer/crew#633 and ADR 0026 landed, so every arm gets the crew's current prompts. Chosen by id from the crew's events (`llm.finished` with a card and a `response_id`, which is LiteLLM's `request_id`), with its outcome read from the same record:
  - 10 Developer calls: 6 first attempts, 4 repairs, including the hardest (mqucifer/sprint-metrics#567 and its kind);
  - 5 QA verdicts and 3 criteria checks;
  - 3 splits, 3 settles, 2 Architect passes.
- **Runs:** 3 per case per arm, each with its own seed. On 2026-10-11 the same prompt thought 3.5k tokens once and 11.4k the next, so one run per case says little.
- **Measures, per call:**
  - valid on the first try; refused, and why; empty; runaway (the call layer's own refusals);
  - prompt, thinking and written tokens; wall time;
  - **how the thinking is spent**, from LiteLLM's `reasoning_content`: hedges per 10k characters (Wait, Actually, Hmm, Alternatively, "let me re-check" and the like) and the share of thinking spent drafting code, JSON or schema. On Qwen3.8-27B, 2026-10-11, across 125 Developer calls: hedging was steady at about 10 per 10k characters whether the call answered or not, while empty answers thought 2.5 times longer, with 31% of it drafting against 15%. The Sponsor's read: the overthinking is the model's own trait, not the prompts', so it's measured here, per model, rather than prompted away;
  - **for the Developer: the answer applied to the story's base commit and the project's checks run in the sandbox,** pass or fail, as the crew's delivery does. Schema-valid isn't crew-valid (flash-next-268);
  - for QA and the criteria check: agreement with what happened (merged and accepted, or returned, and why);
  - for judgement roles: valid, and the record's own checks (rows that contradict, questions left open). Their quality is read by the Sponsor from a sample, not scored.
- **A lever to try on the incumbent, as its own arm:** a logit bias of −2 on hedge tokens ("wait", "maybe", "perhaps"). Reported: 11–19% less thinking on Qwen3.5-4B (a Reddit test on MATH-500), and 27–51% less in the NoWait paper (arXiv, June 2025), with accuracy held. Check first that `logit_bias` reaches SGLang through LiteLLM, and take the token ids from Qwen3.8's tokenizer. The bias touches answers too, so the Developer's must still pass their checks.
- **Decision rule, agreed before running:** a candidate takes a role group if, over its cases, it is no worse on correctness (Developer sandbox pass rate, first-try validity, agreement) and better on at least one of: empty and runaway answers, or median wall time. A tie stays with the incumbent. A result inside the run-to-run spread of the incumbent's own three runs is a tie.

## What it reads

- **The crew's record:** `var/events/tick.jsonl` for the cases' `llm.finished` events (card, `response_id`, `try`, tokens, finish reason) and their outcomes (`card.moved`, `story.returned`, `escalation.decided`).
- **LiteLLM's spend log:** each case's request, by `request_id`, for the prompt to replay. Prompts stay in the run folder, on this Mac.
- **The story's base commit:** from the delivery's record. *To check before running: whether the record holds it for each case. If not, that's a finding for the record, and the base is found by time from the sprint-metrics history, saying so.*

## Harness

Built as `role_fit/` in this repository (mqucifer/model-performance#10). The cases are in `role_fit/cases.py`, with how they were chosen in `role_fit/select.py`; numbers go to `results/role_fit.jsonl` (`results/README.md`).

| Step | Does |
|---|---|
| `uv run role-fit select` | Reads the crew's events for E1's first-try answer calls and prints the cases, one per card per bucket, with production's outcome |
| `uv run role-fit extract` | Copies each case's request from LiteLLM's spend log (Postgres, one SELECT) to the records directory on the Mac |
| `uv run role-fit run --runs 3 [--model <alias>]` | Replays each request as production sent it, streamed and cut off on a runaway as crew does, a seed per run, and scores the answer in its own form beside production's |

**Since the design:** the Developer now works in a session, which the benchmark (`benchmark/`) measures whole. E1's Developer calls are one-shot answers in the two-part form the pinned crew retired, so they're replayed and scored as `dated`: they show the model, not today's crew. The sandbox check of a Developer answer isn't built: a dated answer has no crew left to apply it.

## How to run it

1. **Before:** a Spark slot from the operator. For a candidate, the Sponsor serves it at the planned pause (mqucifer/model-performance#4) and its alias is listed for the builders' key.
2. **Run:** `uv run role-fit run --runs 3`, or `--model <alias>` for a candidate.
3. **Results:** `results/role_fit.jsonl`; each answer and its thinking in `<records>/role_fit/<case>/<run>/`.

## What it changes

Nothing, on any machine. Serving a candidate is the Sponsor's step, with how to put production back.
