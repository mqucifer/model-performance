# Worked examples: the crew's experiments

Six experiments the crew ran by hand in mqucifer/crew, from 2026-09-29 to
2026-10-08, before infra existed. They're here as worked examples of how an
experiment is developed and run. Each has a folder in infra's shape, with a
README and a findings note. **The harnesses stay in mqucifer/crew,** linked at
commit `39e98659cd08fcd595d63c36259b20a74f864be9`: they import the crew's code
(`crew_org`) and read inputs kept beside them, so they run only from a crew
checkout.

| Example | The question | What it shows about developing and running one |
|---|---|---|
| [panel-359](panel-359/) | Does a panel of agents catch more than one, and at what cost on the Spark? | Arms that differ in one thing; serial and parallel; cost read from LiteLLM and SGLang by time window; a replay at a past commit |
| [panel-174](panel-174/) | Would a refinement panel have caught what went wrong with a Goal's first epics? | Inputs collected by a written rule before running; scoring by a stated rule, kept per note; a replay with new code on the same inputs |
| [flash-next-268](flash-next-268/) | Does another model answer the request the 27B leaves empty? | One stored request replayed through the proxy; arms needing a server change the Sponsor makes; answers judged from the spend log, where they stay |
| [multilang-404](multilang-404/) | Can the crew deliver a project that isn't Python, end to end? | A fixture instead of live data; the crew's real loop in a temporary copy; a harness fixed between runs, and each run kept |
| [analyst-231](analyst-231/) | Does a focused context let the Business Analyst split an epic from less? | One case through the crew's own function; prompt size measured before and after |
| [ux-377](ux-377/) | Does a UX Designer's note give each story testable criteria for what a reader sees? | Two roles chained in memory, with stand-in numbers so nothing is posted |

## How they were developed

Each one followed the same steps:
1. **A question from an issue or discussion,** with the cases chosen from real
   work (a story whose first attempt failed, an epic that went wrong).
2. **The crew's own code, not a copy of it.** A harness calls the function the
   crew runs (`review_deploy`, `implement_story`, `propose_design`,
   `split_epic`), so what's measured is what the crew does.
3. **Read-only.** A temporary clone or worktree, nothing posted to GitHub, and
   crew-written code run only in the sandbox.
4. **Arms that differ in one thing,** several runs each, because the model
   doesn't answer the same way twice.
5. **A results file per arm, then an analysis script** that makes the tables
   from it.
6. **A README with the question, the method, the tables, the caveats, and what
   it points to.**

## How they were run

From the crew checkout's root, with `uv sync --extra dev` done once:

```
uv run python experiments/<slug>/<harness>.py <arguments>
```

- **No tick running** (`pgrep -f "crew tick"`): the crew and the experiment
  share the Spark, and each distorts the other's timings.
- **Through LiteLLM on :4000,** on the crew's own model aliases.
- **Per-request numbers** (tokens, time, cache hits) came afterwards, from
  LiteLLM's spend log and SGLang's metrics, for the arm's time window.

## What infra changes for the next one

They were developed before infra's rules, so three things differ from
[README.md](README.md):
- **Results.** They wrote results beside the harness and committed them,
  including model answers. In infra, results go to
  `$INFRA_RESULTS/<slug>/<run-id>/` and are never committed.
- **Inputs.** Some copied issue text and evidence in as `inputs/`. In infra,
  inputs that are content are cited by id or path and fetched at run time.
- **The question.** Theirs came from crew issues and discussions. In infra, it
  comes from a Goal the Sponsor sets.

A harness built here for crew code still runs from the crew checkout's root, as
these did, so it imports the crew's code and finds its `var/` by relative path:
`uv run python ~/Documents/git/infra/experiments/<slug>/run.py`.
