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

**Each case's project record is an authored input** (`benchmark/cases/<case>.project.yaml`).
Every case's base commit has `.crew/project.yaml` in format 2, and crew at the pin reads
only format 3 (mqucifer/crew#847). Without a record it can read, crew falls back to its
defaults: the session starts with "(no record)", and the run gets crew's default image,
setup and checks. So a case carries its record in format 3, and the replay commits it
over the base's before the session starts. The gate and the diff are read against that
commit. A run whose record crew can't read is refused (`record_unreadable`), never run
on the defaults.

How each was made: the base's record is byte-identical to the one its repository
migrated (sprint-metrics 9389a57, crew-presentation 41aa873), so each case takes that
migration with only what the format needs. That's `version: 3`, `serves`, and the
base's own `in_scope` moved to `design.built`; everything else is as the base had it.
**Caveat:** `serves` was written 3 to 10 days after the bases. What the
migrations added that the base records never said is trimmed: DORA's measures in
both, sprint-metrics' new purpose, its two new `out_of_scope` items, and its note on
`GET /trend`. Even so, a need may read a little later than the story's own time.

The five-case run of 2026-10-25 05:24–07:11 UTC ran before this, on crew's defaults.
It found the flaw, and its rows aren't kept. Its records are, under
`records/benchmark/<case>/`, runs `20261025T052435Z` (662), `T054720Z` (596),
`T054956Z` (567), `T060012Z` (124) and `T064644Z` (83). So is the
first one-case run's (`20261025T035757Z`, mqucifer/model-performance#12).

**The 27B baseline, 2026-10-25 08:57–09:56 UTC** (crew 099879f, `crew-code-think`,
a 150-call cap, every case with its authored record, no concurrent tick):

| Case | Ending | Gate | Calls | Tool calls (malformed) | Model s | Wall s |
|---|---|---|---|---|---|---|
| sprint-metrics-662 | done | green | 23 | 38 (0) | 174.3 | 191.7 |
| sprint-metrics-596 | done | green | 23 | 29 (0) | 180.7 | 201.9 |
| sprint-metrics-567 | done | green | 55 | 70 (0) | 680.4 | 705.3 |
| crew-presentation-124 | done | green | 81 | 89 (0) | 1097.8 | 1230.7 |
| crew-presentation-83 | done | green | 32 | 45 (0) | 479.9 | 524.7 |

Before it, `replay crew-presentation-83 --cap 0` checked the image and setup: the
Playwright image and `python tools/setup.py`, exit 0. Its row isn't kept.

**crew-presentation-124 has two rows.** In `replay --all` (run `20261025T091613Z`)
its call 31 failed: LiteLLM answered 500 because the Spark's server disconnected,
at about 66k prompt tokens. The next call, a second later, succeeded. That row
(`interrupted`, `call_failed`, 30 calls) records the lost connection, not the
model, and is kept as it ran. The case was run again straight after
(`20261025T093512Z`), and the table shows that run.

| Field | What it is |
|---|---|
| `ending` | `done`, `blocked` or `interrupted`, as crew's session ended it; or `refused` (it couldn't start) or `crashed` |
| `stop` | what ended it, in a word: a stop (`no_progress`, `backstop`, `ceiling`, `no_tool_call`, `context_full`), an interruption (`call_failed`, `workspace_gone`), or a refusal (`checkout`, `host_venv`, `record_unreadable`, `container_start`, `setup_failed`) |
| `gate_green` | the crew's gate at `done` (autofix, then every check), or null without a `done` |
| `calls` | model calls. A run stops at the call cap (`config.toml`, or `--cap`) as `interrupted` with `call_failed` |
| `tool_calls`, `malformed_tool_calls` | tool calls, and those the session refused under its argument rule: not a JSON object, no such tool, or an unknown or missing argument |
| `model_s`, `wall_s` | seconds waiting on the model, and the run's whole time |
| `*_tokens` | the session's token counts, as LiteLLM reports them |
| `edits_applied`, `test_runs`, `compactions`, `troubles`, `start_chars` | what the session did, by crew's counts |
| `record_authored` | the session read the case's authored record, not the base's own |
