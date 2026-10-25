# Results

One row per run, in `<suite>.jsonl`, holding numbers, flags and short names only.
The run's records (its prompts, answers, events, diff and gate) stay on the Mac,
in the records directory that `config.toml` declares, named by the row's `case`
and `run`. Every field is declared in `common/results.py`, and CI refuses any
other (`scripts/check_no_prompts.py`).

Each row names the crew commit it ran (`crew_commit`) and the LiteLLM alias it
called (`model_alias`). Compare rows only when they share both, or when the
difference is the thing being measured.

**Load:** `concurrent_tick` says whether a `crew tick` ran at any point in the run,
and `tick_calls` how many of its calls were made while one did. The tick shares
the model, so `model_s` and `wall_s` depend on it, while calls, tokens and the
ending don't. Compare times only between rows with the same load. The Spark's
own queue isn't read: nothing probes SGLang directly, and LiteLLM's replies
don't carry it.

## `benchmark.jsonl`: the session replay

**The baseline starts fresh, and doesn't compare with Stage R's numbers.** Stage R
(mqucifer/crew#778, `var/notes/778/replay.md` in crew) ran the replay
experiment's own session, tools and start. The benchmark runs crew's own session
(`crew_org.session`) at the pinned commit, which is what the crew delivers with.
That session has since changed its tools, its endings, its backstop (3 hours,
from 2), and its compaction. So the same case measures a different session, and
the two sets of numbers aren't on the same footing. The surviving Stage R
records are kept in the records directory under `crew-778/`.

| Field | What it is |
|---|---|
| `ending` | `done`, `blocked` or `interrupted`, as crew's session ended it; or `refused` (it couldn't start) or `crashed` |
| `stop` | what ended it, in a word: a stop (`no_progress`, `backstop`, `ceiling`, `no_tool_call`, `context_full`), an interruption (`call_failed`, `workspace_gone`), or a refusal (`checkout`, `host_venv`, `container_start`, `setup_failed`) |
| `gate_green` | the crew's gate at `done` (autofix, then every check), or null without a `done` |
| `calls` | model calls. A run stops at the call cap (`config.toml`, or `--cap`) as `interrupted` with `call_failed` |
| `tool_calls`, `malformed_tool_calls` | tool calls, and those the session refused under its argument rule: not a JSON object, no such tool, or an unknown or missing argument |
| `model_s`, `wall_s` | seconds waiting on the model, and the run's whole time |
| `*_tokens` | the session's token counts, as LiteLLM reports them |
| `edits_applied`, `test_runs`, `compactions`, `troubles`, `start_chars` | what the session did, by crew's counts |

## `cad_eval.jsonl`: the CAD-code evaluation

One row per part's run (`cad_eval/README.md`). `case` is the part. The shared
`tool_calls` and `malformed_tool_calls` mean what they mean above: a malformed call is
one crew's argument rule refuses, here over the evaluation's own tools.

| Field | What it is |
|---|---|
| `tier` | the part's difficulty, 1 (one primitive) to 5 (a fit to another part) |
| `ending` | `done`, `blocked` or `interrupted`; or `refused` or `crashed` |
| `stop` | what ended it, when it isn't `done`: `said` (the model's own `blocked`), `no_tool_call`, `backstop`, `call_cap`, `call_failed`, `workspace_gone`; or a refusal (`no_image`, `container_start`) |
| `image` | the CadQuery image's tag. Its id is in the run's `result.json` |
| `ill_typed_tool_calls` | well formed by crew's rule, but a value of the wrong type (BFCL's type check) |
| `failed_tool_calls` | well formed, but the tool couldn't do it: a path outside the part, a missing file, too much content |
| `reliable_tool_calls`, `tool_reliability` | the calls that did what they asked, and their share of `tool_calls` (null with none). A script that raises is a reliable call and a CAD failure |
| `writes`, `runs`, `inspects` | calls to each tool, well formed or not |
| `compiles`, `closed_mesh`, `within_tolerance` | the part at `done`, checked: null without a `done` |
| `checks_passed`, `checks_total` | the dimension checks behind `within_tolerance`, named in the run's `checks.json` |
| `calls` | model calls. A part stops at its cap (40, or `--cap`; the first run's was 20) as `interrupted` with `call_cap` |
| `calls_to_done` | the calls a part took to reach `done`, or null without one: what the next run's cap is set from |
