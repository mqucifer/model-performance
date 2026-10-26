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

**The harder cases** (mqucifer/model-performance#16, `cad_eval/README.md`) are rows in
this file too: `case` is the case, `tier` is 6 to 8, and `checks_*` count every
member's checks. Five fields are theirs alone, absent from the 30 parts' rows:

| Field | What it is |
|---|---|
| `kind` | `tight` (tier 6), `assembly` (7) or `worded` (8) |
| `parts_total`, `parts_fit` | the case's members, each its own STEP file, and those that passed every check of their own, fits included (null without a `done`) |
| `load_ok` | the simplified load check (a section's bending stress against PLA's strength over 4), or null for a case without one or without a `done`. It never means "strong enough" |
| `fault` | whose the failure is: `model`, `tool`, `infra` or `budget`; null for a case that passed |
| `arm` | the shared field: what the session was given besides the baseline's tools (`skill`), or null for the baseline (`cad_eval/README.md`, "The arms") |
| `concurrency` | the cases the run ran at once. The Spark's load follows it, so times aren't compared across rows; calls and checks are |
| `calls_to_first_compile` | the call after which a `run` first exited 0 with every output file written, or null if none did |

**The harder cases' first run, 2026-10-25 16:45–17:47 UTC** (crew 099879f,
`crew-code-think`, a 20-call cap per case, no concurrent tick), and the rerun of two
of them, 17:48–18:26 UTC, after a fix to the case prompt:

| Case | Kind | Ending | Fault | Checks | Parts fit | Calls | Tool reliability | Model s | Other calls |
|---|---|---|---|---|---|---|---|---|---|
| pin-clevis | assembly | done | | 44/44 | 3/3 | 5 | 0.857 | 355.7 | 5 |
| shelf-bracket | worded | done | infra | 0/1 | 0/1 | 9 | 1.0 | 339.0 | 4 |
| m8-bolt | tight | interrupted (cap) | budget | | | 20 | 1.0 | 1524.2 | 6 |
| caster-wheel | assembly | done | | 72/72 | 5/5 | 12 | 0.95 | 571.5 | 3 |
| pi5-nvme-case | worded | done | model | 30/34 | 0/2 | 5 | 0.833 | 839.9 | 1 |
| shelf-bracket (rerun) | worded | done | model | 7/8 | 0/1 | 10 | 1.0 | 387.4 | 0 |
| m8-bolt (rerun) | tight | interrupted (cap) | budget | | | 20 | 0.95 | 1851.5 | 0 |

- **shelf-bracket's first row is the harness's fault, marked `infra`.** A one-part
  case's prompt said "the file the spec names", and its spec names none. So it wrote
  `bracket.step`, and the clean rerun found no `part.step`. The prompt now names
  `part.step` (`session.system_for`).
  - Its own `bracket.step`, checked in the image as a diagnostic (not a row), passes
    7 of 8: everything but the screw holes.
  - The rerun's `part.step` fails the same one check. Both times its holes are 4.0 mm
    across for 4 mm screws, where ISO 273's clearance holes are 4.3 to 4.8 mm.
- **m8-bolt didn't reach `done` in 20 calls, twice.** The thread is where it breaks.
  - First run: it looked for `cq.makeHelix`, missed `cq.Wire.makeHelix`, and spent
    the run building a B-spline helix through OCP.
  - Rerun: it found `cq.Wire.makeHelix` and a valid helix, then spent the rest on the
    sweep and OCP's names. One call named a tool that isn't here (`edit`), its one
    malformed call.
- **pi5-nvme-case is done, but doesn't fit its boards** (30 of 34 checks):
  - its lid sits at Z = 3.9 to 5.9, through the Pi's parts (4.4 mm on its drawing)
    and far below the USB and Ethernet sockets;
  - its base's wall cuts into the NVMe Base Duo's published 87.6 mm length;
  - it leaves no room for the flex cable.
  
  The port openings, the bosses, the vents and a separate lid pass.
- **`other_calls`** for the first five are every call in LiteLLM's spend log that
  overlapped the row's window (`at` + `wall_s`), less the row's own `calls`.
  - Their events didn't keep the response id then. They do now, and a run counts its
    own calls out by id, as `common/spend.py` does for the benchmark.
  - The builders' key shows exactly the row's own calls in four windows, and one more
    in pin-clevis's (m12-arms' last call).
  - The others were `print-shop`'s: m13-print-settings' proof calls.
- **Overhangs were added after this run,** so these rows don't have them. The passing
  parts' files were measured afterwards, in the image: see the PR.

**Where it breaks, from these seven runs:**
- **Assemblies with a clear spec pass:** three parts and five, with every clearance in
  range, in 5 and 12 calls.
- **Where the model fails, the fault is the model's, not a tool's:**
  - a CadQuery feature it doesn't know its way to (a swept thread);
  - a dimension it isn't given and doesn't know (a screw's clearance hole);
  - a design against real parts where it ignores the parts' published heights and
    sizes it was given (the Pi case).
- **No tool failed:** the one malformed call was a tool name from elsewhere, and the
  measures all finished.

This is evidence for M14's arms: a skill and a signature lookup for the first failure,
engineering references for the second, the boards' models for the third
(mqucifer/model-performance#21, #22, #23). It's five cases, not 21: the arms' baseline
runs all 21.

## `role_fit.jsonl`: which model fits each role

One row per replayed call (`role_fit/`, mqucifer/model-performance#10). `case` is the
call's `response_id` in production, and `run` ends with its seed. Each case is one
first-try answer call from E1 (mqucifer/crew#583) on sprint-metrics, 2026-10-11 17:51 to
2026-10-13 19:42 UTC, sent again as production sent it.

**Compare `valid` with `prod_form_valid`, not `prod_valid`.** `prod_valid` is crew's own
verdict, which also ran the step's rules on its answer model. `prod_form_valid` is
production's answer scored as the replay's is. On the 26 cases the scorer agrees with
crew's verdict on 24; the other two crew refused under its answer model's own rules
(a list left empty, an implementation that edits nothing).

**`dated` cases** asked for a form the pinned crew no longer asks for: E1's two-part
answers (the Developer's), or a model whose schema has changed since. They're scored on
the request's own form, and say what the model does with that prompt, not what today's
crew would do.

**The 27B baseline, round 1, 2026-10-25 18:42–21:14 UTC** (crew 099879f, each request's own
alias, `crew-code-think` or `crew-analysis`, seed 1, one call per case, no concurrent tick).
From 19:25 UTC m14-hard-eval's CAD baseline shared the Spark, 4 sessions to this one (the
Sponsor's rule for quality runs): 17 of the 26 rows have `other_calls` above 0. Validity,
empty and runaway answers don't depend on load. Times do, so read them only beside
`other_calls`.

| Bucket | Cases | Valid | Production's answer, same scorer | Crew's verdict | Empty, runaway, cut | Median s (production) | Median thinking tokens (production) |
|---|---|---|---|---|---|---|---|
| dev-first | 6 | 4 | 5 | 3 | 0 | 352 (540) | 4,824 (12,918) |
| dev-repair | 4 | 4 | 2 | 2 | 0 | 350 (316) | 6,330 (5,416) |
| qa-verdict | 5 | 5 | 5 | 5 | 0 | 230 (151) | 2,798 (2,541) |
| criteria | 3 | 3 | 3 | 3 | 0 | 570 (226) | 11,429 (7,428) |
| split | 3 | 3 | 3 | 3 | 0 | 723 (408) | 11,428 (10,742) |
| settle | 3 | 3 | 2 | 2 | 0 | 144 (118) | 3,049 (3,582) |
| architect | 2 | 2 | 2 | 2 | 0 | 409 (285) | 6,195 (4,541) |
| **execution** | 18 | 16 | 15 | 13 | 0 | 326 (302) | |
| **judgement** | 8 | 8 | 7 | 7 | 0 | 409 (285) | |

- **The two invalid answers are both the Developer's two-part form** (`block_names`): the
  fields name their blocks as `@@b1` or `@@b1@@`, not `b1`. Production's answer to one of
  them (e14cc9f1) made the same kind of mistake, and crew refused it.
- **No empty, runaway or cut answer in 26.** Production had one empty answer among these
  cases (f761a097); its replay answered, in its form.
- **Thinking varies call to call more than the averages show:** the same criteria check
  (7a627c0d) thought 12,807 tokens against production's 2,942. One round says little per
  case, which is why model-fit-29 asks for three.
- **Times:** the 9 rows with no other call on the proxy (the Developer's, before the CAD
  run, and one settle) took a median 306 s against production's 499 s for the same
  requests. Production ran beside the crew's own ticks, so neither side was idle.

| Field | What it is |
|---|---|
| `bucket`, `group` | the kind of call (`dev-first`, `dev-repair`, `qa-verdict`, `criteria`, `split`, `settle`, `architect`) and its role group, `execution` or `judgement` |
| `ending` | `done`, or `refused` (`no_request`: not extracted), `interrupted` (`call_failed`, `call_cap`), `crashed` |
| `form` | `json_schema`, `two_part` or `free` |
| `valid`, `why` | the answer in its form, and why not in a word: `empty`, `runaway`, `length`, `not_json`, `schema`, `model`, `blocks`, `block_names`, `cut_at_quote` |
| `empty`, `runaway`, `cut` | no answer; run on as whitespace and cut off, as crew's call layer does; stopped at its token limit |
| `thinking_chars`, `hedges_per_10k` | the thinking's length, and its hedges per 10k characters (model-fit-29's list) |
| `prod_*` | the same request in production, from crew's events and LiteLLM's log |

## Question 2, the skill arm (mqucifer/model-performance#21): what a CadQuery skill and a lookup close

**Answer:**
- **Closed:** the CadQuery skill and `lookup` fixed the failures that were about
  CadQuery's API. That's m8-bolt's thread (tight), cable-comb's guessed method name,
  and spool-holder (worded).
- **Not closed:** the missing engineering values (screw clearance) and the fits
  against real parts (the Pi 5 case).
- **The cost:** reasoning doubled, the first compiling part came at call 7 instead of
  2, and two tight cases the baseline passes ran out of calls. So 10 of 21 pass
  against the baseline's 12.

**The runs:**
- The baseline ran 2026-10-25 19:27–21:16 UTC. The skill arm ran 22:24 UTC to 01:40
  UTC on the 26th.
- Both: crew 099879f, `crew-code-think` (thinking on), 4 cases at once, a 20-call cap,
  one run per case.
- The skill arm shared the Spark with a crew tick throughout (`concurrent_tick`).
- Calls are capped by count, so the passes don't depend on that. No timing is
  compared.

| | Baseline | Skill |
|---|---|---|
| Pass | 12 / 21 (tight 6, assembly 4, worded 2) | 10 / 21 (tight 4, assembly 3, worded 3) |
| The harness's own faults (`tool`), not counted for or against | drawer-cabinet | drawer-cabinet |
| Calls | 156 | 267 |
| Reasoning tokens | 343,496 | 715,825 |
| Median call to a first compiling part | 2 | 7 |
| Runaways | 1 (bolt-nut) | 0 |
| Other calls through the proxy meanwhile | 526 | 1,435 |

| Kind | Case | Baseline | Failed checks | Calls (first compile) | Skill | Failed checks | Calls (first compile) |
|---|---|---|---|---|---|---|---|
| tight | living-hinge | pass |  | 5 (2) | pass |  | 11 (4) |
| tight | press-fit-pin | pass |  | 4 (2) | pass |  | 6 (3) |
| tight | snap-hook | pass |  | 12 (6) | pass |  | 8 (6) |
| tight | dovetail-slider | pass |  | 4 (2) | budget (call_cap) |  | 20 (5) |
| tight | print-in-place-hinge | pass |  | 6 (4) | model (done) | volume | 12 (9) |
| tight | spur-gear | pass |  | 6 (4) | budget (call_cap) |  | 20 (3) |
| tight | m8-bolt | model (done) | changes.flanks, share.crests, share.flanks | 6 (4) | pass |  | 14 (4) |
| assembly | pin-clevis | pass |  | 5 (2) | pass |  | 13 (7) |
| assembly | shaft-bushing-collar | pass |  | 4 (2) | model (done) | bushing:volume, shaft:gap.bushing.distance, shaft:gap.bushing.interference | 12 (7) |
| assembly | drawer-cabinet | budget (call_cap) |  | 20 (2) | tool (done) | closed_mesh | 10 (7) |
| assembly | gear-pair | budget (call_cap) |  | 20 (None) | model (done) | gear-a:volume | 14 (12) |
| assembly | bolt-nut | model (runaway) |  | 0 (None) | budget (call_cap) |  | 20 (None) |
| assembly | snap-enclosure | pass |  | 5 (2) | pass |  | 15 (13) |
| assembly | caster-wheel | pass |  | 4 (2) | pass |  | 16 (14) |
| worded | shelf-bracket | pass |  | 4 (2) | model (done) | holes.screws | 6 (4) |
| worded | tube-clip | model (done) | holes.screws, share.takes_tube, share.wraps | 8 (5) | model (done) | share.takes_tube | 12 (10) |
| worded | d-shaft-knob | pass |  | 5 (2) | pass |  | 15 (12) |
| worded | wall-hook | model (done) | holes.screws | 11 (8) | model (done) | span.y, within.y | 6 (4) |
| worded | cable-comb | model (done) | measured | 17 (None) | pass |  | 15 (8) |
| worded | spool-holder | model (done) | holes.screws, share.carries_width | 6 (2) | pass |  | 9 (7) |
| worded | pi5-nvme-case | model (done) | lid:share.ethernet, lid:share.hdmi_0, lid:share.hdmi_1, lid:share.usb_29, lid:share.usb_47, lid:share.usb_c, lid:vents.over_the_pi | 4 (2) | model (done) | base:share.boss_3.5_3.5, base:share.boss_3.5_52.5, base:share.boss_61.5_3.5, base:share.boss_61.5_52.5, base:share.flex_cable | 13 (11) |

A case's calls column is its calls, then (in brackets) the call after which a run
first wrote every output. A blank failed-checks cell with a `budget` verdict means
the case never reached `done`.

**What it fixed:**
- **m8-bolt passes, 19/19, for the first time in five runs.**
  - It read `cadquery-threads-helices` and looked up `makeHelix` and `Solid.sweep`.
    Then it followed the reference's recipe: a helix longer than the thread,
    `isFrenet=True`, fused onto a core and cut to length.
  - **Caveat:** that recipe was written by me, from what made my own reference thread
    valid. It's general CadQuery practice, not this case's numbers. But it's close
    to the answer, so this pass overstates what a skill written blind would do.
- **cable-comb passes.** The baseline's script crashed on a guessed method
  (`isClosed`), the failure `lookup` is for.
- **spool-holder passes.** It built a spindle through the hub's hole, where the
  baseline built a cradle round it.
- **gear-pair reaches `done`** (45 of 46: gear A's volume 2.3% over). The baseline
  ran out of calls.
- **tube-clip improves** from 6 to 8 of 9. It now wraps the tube and its screw holes
  have clearance. It fails only its bore, a deliberate interference grip, against a
  limit that's this evaluation's own choice.
- **pi5-nvme-case improves** from 27 to 29 of 34:
  - both boards are now kept out, 0.5 mm clear;
  - the lid sits above the Pi's published 4.4 mm parts.
  
  It fails the four bosses under the holes and part of the flex cable's path.
  **Not caught:** its lid, at Z = 8.4, is still below the USB and Ethernet sockets,
  whose heights aren't published, so no check holds them.

**What it didn't fix, and the next arm for each:**
- **The Ø4.0 screw clearance** (4 mm screws in 4.0 mm holes; ISO 273 gives 4.3 to
  4.8).
  - It's in 6 runs today: shelf-bracket three times (including the skill arm),
    wall-hook, tube-clip and spool-holder in the baseline.
  - The skill holds no engineering values. → **#22, engineering references.**
- **Fit against real parts:** the Pi case's bosses, flex path and socket heights.
  → **#23, the component library.** The Pi 5's own STEP files would give the
  sockets' heights.
- **bolt-nut** never reaches `done`, in any arm. Its baseline call ran away (the
  only runaway), and the skill arm's ran out of calls.

**What it cost:**
- **The first pass after reading the skill is much longer.** The baseline's longest
  call today was 44,843 completion tokens, against 54,309 (gear-pair) and 62,218
  (bolt-nut), each straight after reading the skill.
- **Total reasoning doubled,** and the first compile came 5 calls later.
- **dovetail-slider and spur-gear,** which the baseline passes in 4 and 6 calls, ran
  out of calls.
  - dovetail-slider had the part right, to the reference's volume, by its 6th call.
    It spent the rest checking its fit, as the skill's `cadquery-assemblies-fits`
    suggests, and never called `done`.
  - The cases it passes took about 2 to 4 times the calls.
- **Losses that may be variance:** shaft-bushing-collar (its bushing's bore not cut)
  and print-in-place-hinge (volume 2.1% over) passed in the baseline.
  - With one run per case, a single case's flip is weak evidence.
  - The totals' difference (12 against 10) is no bigger than the number of cases
    that flipped each way. So the net count doesn't say the skill is worse; the
    calls spent checking, and the two caps, do.

**The evaluation's own faults, found in these runs:**
- **drawer-cabinet, both runs:** the spec's finger hole (Ø20 at Z = 40) was tangent
  to the drawer's top at Z = 50. Cut as the spec said, it leaves one non-manifold
  edge, so the mesh isn't closed.
  - In the skill arm, the drawer passed all 30 dimension and fit checks and failed
    only on that mesh.
  - In the baseline, it had the drawer right at its 2nd call (59,999 mm³) and spent
    its other 18 chasing the open mesh, to the cap.
  - Both rows are kept as they ran, re-marked `tool`.
  - The spec now centres the hole at Z = 38, 2 mm below the top edge. Its reference
    passes and its wrong one fails in the image. The case runs again, on the
    baseline and the skill, when the Spark allows.
- **bolt-nut, baseline:** its one call thought towards the 65,536-token limit, and
  the client's one-hour timeout ended it (`cad_eval/README.md`, "Runaways"). The row
  is re-marked as a runaway, the model's.
- **Two limits that are this evaluation's choice, not a standard,** decide two
  failures: tube-clip's bore (at least 19.9 mm for a 20 mm tube) and wall-hook's width
  (40 to 80 mm for a 40 mm strap).

**For #22 and for M14:**
- The skill shows that context does close failures: three of the baseline's nine,
  all about CadQuery's API. The ones left are engineering values and real parts, not
  CadQuery.
- So the next arm, #22's references (clearances, fits, fasteners), is aimed squarely
  at the most frequent failure today. #23's library is aimed at the Pi case.
- The skill's cost is a finding too:
  - **The fit-checking advice spends calls.** #22's references should be read for
    values, not as a procedure to verify.
  - **A leaner skill** (a short `SKILL.md`, or no fit-checking section) is worth a
    look before the combined arm.
- **Nothing here points to training yet.** Every failure the skill closed was
  knowledge it was handed. The ones left are knowledge the next two arms hand it.
  That's evidence against an adapter, unless #22 and #23 leave failures standing.

## Question 2, the references arms (mqucifer/model-performance#22): what engineering values close

**Answer:**
- **The references close the failures that were missing values.**
  - The screw clearance came out right in 4 of 4 runs with the references alone,
    against 1 of 5 in the baseline.
  - The Pi 5 case passes 34/34 for the first time.
  - So the references alone are the best arm: 14 of 21, against the baseline's 12 and
    the skill's 11.
- **With the CadQuery skill they don't add:** 11 of 21. Reading both sets costs
  calls, and the worded cases fall to 1 of 7.
- **What's left in every arm is hard CadQuery geometry.** Gears and threads pass in
  at most one arm each, so not reliably anywhere.

**The runs** were 2026-10-26, crew 099879f, `crew-code-think` (thinking on), with a
20-call cap and one run per case:
- **refs:** 02:22 to 06:21 UTC, 1 case at a time until 04:20 (a tick was refining a
  Goal), then 4;
- **skill-refs:** 06:21 to 09:11, at 4;
- **the reruns:** 09:11 to 10:38.

Calls are capped by count, so passes don't depend on the load, and no timing is
compared.

**The four arms**, each case's verdict, then its calls:
- `cap` means it never reached `done` in 20 calls.
- `fail n/m` means it reached `done` and passed n of m checks.
- **drawer-cabinet's baseline and skill cells are today's reruns** on the fixed spec.
  The first rows were the harness's own fault (the tangent finger hole). With the
  rerun, the skill arm passes 11, not the 10 reported in #24.

| Kind | Case | Baseline | Skill | Refs | Skill + refs |
|---|---|---|---|---|---|
| tight | living-hinge | pass, 5 | pass, 11 | pass, 4 | pass, 4 |
| tight | press-fit-pin | pass, 4 | pass, 6 | pass, 5 | pass, 13 |
| tight | snap-hook | pass, 12 | pass, 8 | pass, 7 | fail 21/22, 18 |
| tight | dovetail-slider | pass, 4 | cap, 20 | pass, 6 | pass, 11 |
| tight | print-in-place-hinge | pass, 6 | fail 21/22, 12 | pass, 5 | pass, 8 |
| tight | spur-gear | pass, 6 | cap, 20 | cap, 20 | cap, 20 |
| tight | m8-bolt | fail 16/19, 6 | pass, 14 | cap, 20 | fail 16/19, 9 |
| assembly | pin-clevis | pass, 5 | pass, 13 | pass, 5 | pass, 12 |
| assembly | shaft-bushing-collar | pass, 4 | fail 38/41, 12 | pass, 5 | pass, 11 |
| assembly | drawer-cabinet | cap, 20 | pass, 5 | pass, 5 | pass, 8 |
| assembly | gear-pair | cap, 20 | fail 45/46, 14 | cap, 20 | cap, 20 |
| assembly | bolt-nut | runaway, 0 | cap, 20 | cap, 20 | pass, 10 |
| assembly | snap-enclosure | pass, 5 | pass, 15 | cap, 20 | pass, 7 |
| assembly | caster-wheel | pass, 4 | pass, 16 | pass, 7 | pass, 8 |
| worded | shelf-bracket | pass, 4 | fail 7/8, 6 | pass, 9 | pass, 10 |
| worded | tube-clip | fail 6/9, 8 | fail 8/9, 12 | fail 8/9, 16 | fail 8/9, 15 |
| worded | d-shaft-knob | pass, 5 | pass, 15 | fail 13/14, 7 | cap, 20 |
| worded | wall-hook | fail 6/7, 11 | fail 5/7, 6 | pass, 11 | fail 6/7, 14 |
| worded | cable-comb | fail 0/1, 17 | pass, 15 | pass, 4 | fail 9/10, 11 |
| worded | spool-holder | fail 6/8, 6 | pass, 9 | pass, 16 | cap, 20 |
| worded | pi5-nvme-case | fail 27/34, 4 | fail 29/34, 13 | pass, 14 | fail 31/34, 9 |

| | baseline | skill | refs | skill-refs |
|---|---|---|---|---|
| Pass | 12 / 21 | 11 / 21 | 14 / 21 | 11 / 21 |
|   tight | 6 | 4 | 5 | 4 |
|   assembly | 4 | 4 | 4 | 6 |
|   worded | 2 | 3 | 5 | 1 |
| Model faults | 7 | 7 | 2 | 6 |
| Call cap | 2 | 3 | 5 | 4 |
| Harness (tool) / infra | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Runaways | 1 | 0 | 0 | 0 |
| Calls | 156 | 262 | 226 | 258 |
| Reasoning tokens | 330,818 | 709,088 | 687,134 | 776,122 |
| Median call to first compile | 2 | 7 | 4 | 9 |
| Other calls meanwhile | 491 | 1,375 | 597 | 702 |

**Second samples** (reruns of the same case and arm, on the streaming sender):
- **gear-pair, baseline:** cap again (20 calls), as on 2026-10-25.
- **bolt-nut, baseline:** cap (20). That's its third baseline run: one runaway, two
  caps.

**The screw clearance, run by run** (the `holes` check: a hole of Ø4.2 to 5.2 for a
4 mm screw, along the right axis):

| Arm | Clearance right | Runs |
|---|---|---|
| Baseline | 1 of 5 | shelf-bracket passed once in three; wall-hook, tube-clip and spool-holder all Ø4.0 |
| Skill | 3 of 4 | shelf-bracket missed |
| Refs | **4 of 4** | shelf-bracket read `ref-fasteners` and drew Ø4.5, "clearance for 4 mm wood screw (practice value)" |
| Skill + refs | 2 of 3 measured | wall-hook chose Ø4.5 from `ref-fasteners`, but cut it along the wrong axis; spool-holder never reached `done` |

**What the references fixed:**
- **The screw clearance,** above: the value the baseline lacked in 4 of 5 runs.
- **pi5-nvme-case passes 34/34**, its first pass in five runs.
  - It read all four references.
  - Its base and lid keep out of both boards, with a boss under each hole and room for
    the flex cable, and its lid now reaches Z = 17.
  - **Caveat:** the sockets' heights aren't published, so a pass means it fits what's
    published. #23's component references settle the rest.
- **The worded cases go from 2 to 5 of 7,** and model faults from 7 to 2.

**What they didn't fix, and why:**
- **Gears and threads.** spur-gear, m8-bolt, gear-pair and bolt-nut hit the cap with
  the references, as they mostly do everywhere. They hold no CadQuery, and these
  failures are building the geometry, not choosing a value.
- **d-shaft-knob** (13/14): its D-bore is 6.9 mm³ into the shaft, over my 1 mm³
  allowance for "pushes on snugly". That allowance, like tube-clip's bore (8/9 in
  every arm), is this evaluation's own choice, not a standard.

**Skill and references together** (`skill-refs`), 11 of 21:
- **Assemblies are best combined, 6 of 7.** bolt-nut passes (34/34) for the first time
  in seven runs. It read only the CadQuery threads and fits references, not the
  engineering ones. It's one run, and the thread recipe is the one I wrote (#24's
  caveat).
- **Worded cases fall to 1 of 7.** Two hit the cap (d-shaft-knob, spool-holder), which
  pass with either set alone. wall-hook had the right value on the wrong axis.
  pi5-nvme-case came to 31/34, where refs alone passed it.
- **The cost:** the most reasoning of any arm (776k tokens), and the latest first
  compile (median call 9).

**One run per case, and how much that matters:**
- Several cases flip between arms with no clear cause: snap-hook,
  print-in-place-hinge, shaft-bushing-collar, snap-enclosure, d-shaft-knob,
  cable-comb.
- A single flip is weak evidence; a pattern across cases isn't. Two patterns hold:
  - the screw clearance, every run with the references;
  - the gears and threads, failing in most runs of every arm.

**What this means for #23 and for M14's training decision:**
- **The references did what knowledge should.** The value failures are gone with them,
  and the Pi 5 case passes on published data. #23 adds the parts' own heights, the one
  thing the Pi case can't yet be checked on.
- **Load less, not more:** the references alone beat both sets together. Before the
  combined arm with #23, the context to trim is clear. Offer the CadQuery skill's
  threads and fits topics only for the cases that need them, or keep `SKILL.md` short.
- **What's left is the gears and threads.** They fail in most runs of every arm, and
  pass in at most one each. That's the only failure that looks like a capability
  rather than missing knowledge. But it's also where the variance is widest.
- So before training is considered for it:
  - run those four cases several times per arm (3 to 5), to tell a gap from noise;
  - try the planned measure-tool arm (checking a part's features before `done`),
    since those cases spend their calls guessing whether the geometry is right.
- **Nothing here argues for an adapter yet.**

**The harness, fixed in these runs:** two runs of one case in the same second (an arm
and a rerun, in two processes) shared a run id. The records refused the second rather
than overwrite, so drawer-cabinet's baseline rerun didn't run the first time. A taken
id now gets the next suffix (`cad_eval/run.py`, `fresh_run`), and the case was run
again.
