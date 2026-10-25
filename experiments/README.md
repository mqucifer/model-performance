# Experiments

*Moved here from mqucifer/infra's `experiments/` at 2d0a8c0 (mqucifer/project-print
ADR 0002), unchanged. Where it says "here" or "infra", read this repository; its
results go to `~/infra-results` until each experiment moves to the records
directory in `config.toml`. Model fit (mqucifer/infra#29) is refiled here as mqucifer/model-performance#10.*

An experiment answers one question from a Goal by running something: against
the stack through LiteLLM, against the crew's record, or both. Most test an
LLM setup on the Spark: a model, how it's served, or how it holds up under
the crew's load. It's developed
here and run elsewhere, from the checkout it needs. What it showed comes back
as a short findings note. The conclusion, and what happens next, is the
Sponsor's.

## Where the question comes from

- **A Goal the Sponsor sets.** Each experiment's README names its Goal. The
  crew doesn't set questions of its own.
- A finding can suggest a next question. The note says so under "What it
  suggests", and the Sponsor decides whether it becomes a Goal.

## One folder per experiment

```
experiments/<slug>/
  README.md     the Goal, the question, the method, what it reads, how to run it
  FINDINGS.md   what it showed, its limits, what it suggests; the conclusion is the Sponsor's
  <harness>     the code that runs it, and analyses its results
  inputs/       only inputs that carry no content: ids, hashes, settings
```

- **The slug** is a short subject and the number of the issue it serves, such
  as `capacity-12`. Examples brought from the crew keep their crew names.
- **Start from [`_template/`](_template/).** Copy it, rename the folder, and
  fill in the README before the harness exists: the method and the decision
  rule are agreed before anything runs.
- **Inputs that are prompts or answers aren't copied in.** Cite them by id,
  hash or path in the local record, and have the harness fetch them at run time.

## Scripts, properly

A harness is a script someone else can rerun from the README alone:

- **Arguments, not edits.** Arms, run counts, aliases and seeds are arguments,
  with `--help`. Nothing is changed in the file to run another arm.
- **Through LiteLLM on :4000,** on a named alias. A setup that needs a new alias
  or a server change lists it in the README as a step for the Sponsor.
- **Seeds where the server honours them,** so one sample isn't counted as five.
  `experiments/flash-next-268` found a server that fixes its own.
- **Read-only.** It changes no machine and posts nothing.
- **Each run is a new folder,** with its `run.json` written first, so a run cut
  short still says what it was.
- **Analysis is its own script,** reading the run folders, so the numbers can be
  recomputed without calling the model again.
- **Existing tools before new ones.** For serving capacity, SGLang's
  `bench_serving` or GuideLLM, fed with the crew's real prompt sizes; the
  crew-specific parts are the harness's own.

## Where results go

Raw runs and results never enter the repository. A harness writes each run to

```
$INFRA_RESULTS/<slug>/<run-id>/
```

`INFRA_RESULTS` defaults to `~/infra-results`, outside every clone and
worktree, so removing a worktree never loses a run. `<run-id>` is the run's
start in UTC, `YYYYMMDDTHHMMSSZ`, with a short label if there are several arms.
In Python:

```python
import os
from datetime import UTC, datetime
from pathlib import Path


def run_dir(slug: str, label: str = "") -> Path:
    root = Path(os.environ.get("INFRA_RESULTS", "~/infra-results")).expanduser()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + (f"-{label}" if label else "")
    path = root / slug / run_id
    path.mkdir(parents=True)
    return path
```

Each run folder starts with a `run.json` saying what ran:
- the infra commit of the harness, and the crew commit if it ran crew code;
- the start and end time, and each arm;
- the model aliases it called;
- the record ids it read: ticks, runs, cards and calls.

The run folder may hold prompts and answers, because it stays on this Mac. The
findings note carries only names, ids and numbers, like everything else here.

## Rules for running one

- **Model traffic goes through LiteLLM on :4000,** never straight to the Spark.
- **The crew is idle.** No tick runs during an experiment that measures the
  stack, or each disturbs the other. Check with `pgrep -f "crew tick"`.
- **Nothing is changed on a machine by the experiment.** If an arm needs a
  server setting, the README lists it as a step for the Sponsor, and how to put
  production back afterwards.
- **It reads the crew's record by id,** never by time or prose: tick, run, card
  and call ids, as `docs/the-crews-record.md` and `docs/reference/records.md` in
  mqucifer/crew describe.
- **A join with no shared id is by time, and says so.** LiteLLM's spend log and
  SGLang's logs don't carry the crew's ids, so matching a call to them is by
  time, within a stated window. The findings note gives the window and how many
  calls matched.
- **A number has a baseline and a sample size,** and the note says how much of
  it is noise.

## What an experiment needs from the record

What the worked examples needed, so the next one checks for it first:
- **Which code ran:** the crew commit, and whether its tree was dirty.
- **Each model call joined to its run and card,** with its prompt size, answer
  size, thinking tokens, finish reason and duration.
- **Which rule decided** a block, a return or an escalation, by name, as
  `rule` and `failure_kind` now record.
- **The serving settings in force** (image, speculative decoding, cache, KV
  type), which the crew's record doesn't hold. Today they're read from the
  Spark by hand.

When an experiment finds something the record can't answer, its findings note
says what was missing. That becomes a question for a Goal, not a change made
here.
