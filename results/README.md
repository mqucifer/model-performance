# Results

One row per run, in `<suite>.jsonl`, holding numbers, flags and short names only.
The run's records (its prompts, answers, events, diff and gate) stay on the Mac,
in the records directory that `config.toml` declares, named by the row's `case`
and `run`. Every field is declared in `common/results.py`, and CI refuses any
other (`scripts/check_no_prompts.py`).

Each row names the crew commit it ran (`crew_commit`) and the LiteLLM alias it
called (`model_alias`). Compare rows only when they share both, or when the
difference is the thing being measured.

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
