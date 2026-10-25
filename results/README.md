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

`other_calls` counts every other call through the proxy that overlapped the run:
ticks, builders, and anything else sharing the Spark (`common/spend.py`). It reads
LiteLLM's own log, `LiteLLM_SpendLogs`, with a SELECT, and leaves out the run's own
calls by request id; `other_aliases` names their key aliases. It's null when the log
can't be read, never 0. **Read times as under load wherever `other_calls` is above 0.**
`arm` is the one setting changed against the baseline, or null for the baseline.

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

**The arms, sprint-metrics-567, 2026-10-25 15:46–16:45 UTC** (mqucifer/model-performance#5,
`replay --arm`, crew 099879f, a 150-call cap, one run each; `benchmark/arms.py` names
each arm's request field and value). One run per arm, so each line shows a direction,
not a rate:

| Arm | Sets | Ending | Gate | Calls | Reasoning tokens, per call | Answer tokens | Model s | Cached | Compactions | Other calls |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | `crew-code-think`: `reasoning_effort: low` | done | green | 55 | 5,832, 106 | 19,540 | 680.4 | 97.9% | 0 | (none read) |
| think-off | `chat_template_kwargs: {enable_thinking: false}` | done | green | 124 | 0, 0 | 18,899 | 682.6 | 97.9% | 1 | 0 |
| effort-medium | `crew-analysis`: `reasoning_effort: medium` | done | green | 53 | 15,114, 285 | 11,620 | 907.9 | 97.6% | 0 | 0 |
| reasoning-dropped | `reasoning_content` left out of each request | done | green | 57 | 21,723, 381 | 14,874 | 1056.8 | 97.6% | 0 | 6 |
| compact-50 | compaction at 50k estimated tokens | blocked (`context_full`) | - | 46 | 13,847, 301 | 8,815 | 780.1 | 88.7% | 10 | 27 |

Answer tokens are completion tokens less reasoning tokens; cached is cached tokens
over prompt tokens.
- **Thinking off** reached `done` too, but took 124 calls to the baseline's 55, with
  the same model time and 2.3× the prompt tokens (10.6M). Its one compaction came when
  the history passed 125k. Thinking bought fewer, better-aimed calls, not a different outcome.
- **More thinking, less said:** at medium effort, reasoning per call rose 2.7×, the
  answer fell 41%, and the calls stayed level (53). Model time rose by a third with no load.
- **Dropping the kept reasoning made each call think more** (381 tokens a call, 3.6×)
  and slower. Six of its calls overlapped m10-qa-tasks's QA session, so its time is under load.
- **compact-50: crew's masking at the pin can't hold a session under 50k.** Compaction
  fired first before call 13 (50.4k → 29.8k), then before calls 23, 28, 29, 32, 38,
  44, 45, 46 and 47, freeing less each time (the last, 53.5k → 50.4k). Then the session
  stopped as `context_full`. What masking leaves is the start and what the model wrote.
  It ran no tests and made 8 edits. That's the form research-compaction.md moves past,
  filed as mqucifer/crew#906. Its time is under load: 24 calls of the QA session and
  3 under the `print-shop` key overlapped it.
- **Not kept as a row:** a `budget-128` run (15:45 UTC, `custom_params:
  {thinking_budget: 128}`) ended at call 6 of 6, at 772 reasoning tokens. The Spark's
  SGLang has neither `--enable-strict-thinking` nor `--enable-custom-logit-processor`,
  so a budget isn't enforced. The Sponsor dropped the budget arm the same day: long
  thinking is a symptom of what the context or the tools didn't give. Its records stay
  on the Mac.

**What the crew already spent thinking, per role** (observed in production, not a
controlled arm; `python -m benchmark.spent --since 2026-10-19T00:00Z --until
2026-10-25T15:44Z`). From crew's event log, read-only: sprint-metrics Sprints 30–35 and
15, crew-presentation Sprints 31 and 15. Each role ran on its own alias, stories and
load:

| Role | Alias | Calls | Reasoning / completion | Reasoning per call: median, p90, max | Answer tokens | Cut off | Empty | Compactions |
|---|---|---|---|---|---|---|---|---|
| Developer | crew-code-think | 2,087 | 0.71 | 63, 1,312, 17,390 | 473,244 | 0 | 0 | 14 |
| QA Engineer | crew-code-think | 1,342 | 0.88 | 287, 4,141, 27,213 | 253,098 | 0 | 0 | 0 |
| Business Analyst | crew-analysis | 555 | 0.83 | 287, 4,333, 18,541 | 147,145 | 0 | 0 | 4 |
| DevOps Engineer | crew-code-think | 385 | 0.89 | 187, 3,103, 32,769 | 60,460 | 1 | 0 | 0 |
| Architect | crew-analysis | 321 | 0.77 | 135, 4,077, 25,859 | 122,367 | 0 | 0 | 0 |
| UX Designer | crew-analysis | 288 | 0.84 | 118, 4,489, 11,841 | 70,159 | 0 | 0 | 0 |
| Product Owner | crew-analysis | 194 | 0.86 | 343, 5,379, 32,770 | 55,607 | 1 | 0 | 0 |
| Code Reviewer | crew-code-think | 61 | 0.94 | 3,812, 8,118, 12,875 | 15,095 | 0 | 0 | 0 |
| Scrum Master | crew-analysis | 6 | 0.95 | 5,344, 10,498, 10,498 | 2,155 | 0 | 0 | 0 |

- Every role but the Developer (0.71) and the Architect (0.77) spends over four-fifths
  of its output thinking. For most roles the median is small and the tail long, with a p90
  14 to 38 times the median. Those tails are the calls to read for what the context or
  the tools didn't give. The Code Reviewer and the Scrum Master think long on every
  call instead (p90 about twice the median).
- **Compaction has fired live,** 18 times since 2026-10-21, all in sprint-metrics: 14
  Developer sessions and 4 Business Analyst ones, up to three times in one session.
  The Developer's controlled numbers are the arms above. Replaying calls per role
  through other models is mqucifer/model-performance#10's.

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
| `max_call_reasoning_tokens` | one call's most reasoning tokens, in an arm's run; null in the baseline's |
| `sessions`, `serving`, `batch` | set on a concurrent run's sessions only (`tuning/`): how many ran at once, the Spark's SGLang setting (`record`, or e.g. `mem-fraction-static:0.88`), and the run's `tuning.jsonl` row. Absent: one session, on the record |

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

## `tuning.jsonl`: concurrent runs on the Spark

One row per `concurrent` run (`tuning/README.md`, mqucifer/model-performance#7). Its
sessions' own rows are in `benchmark.jsonl`, with this row's `run` as their `batch`.
The shared fields are the sessions' summed (`calls`, `*_tokens`, `model_s`,
`tick_calls`), except `wall_s`, which is the whole run's.

| Field | What it is |
|---|---|
| `sessions`, `serving` | how many ran at once, and the SGLang setting under test (`record`: infra's launch as it is) |
| `workspace_memory`, `docker_free_gib` | each workspace's cap, and Docker's free memory before the run |
| `stories`, `done`, `gate_green` | sessions started, ended `done`, and passed first time: the gate green at `done` |
| `story_wall_s_mean`, `story_wall_s_max` | wall-clock per story, over its sessions |
| `ttft_p50_s`, `ttft_p95_s` | SGLang's time to first token over the run's requests |
| `queue_max`, `running_max` | the most requests waiting, and running, at once |
| `cache_hit_mean`, `kv_use_max` | the radix cache's hit rate, and the most of the KV cache in use (0 to 1) |
| `spec_accept_mean`, `gen_throughput_mean` | the draft's accepted tokens per step, and tokens generated per second |
| `grafana` | whether the Spark's series were read from Grafana; false leaves them null |

The Spark's numbers are read from Grafana (Alloy's scrape of SGLang's metrics), never
from the Spark, at a 15 s step: a peak shorter than that can be missed.
