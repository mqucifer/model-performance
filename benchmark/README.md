# The benchmark: the session replay

Does crew's Developer session converge on stories that really failed, and at what
model time and tokens? Moved from crew's `experiments/session_replay/`
(mqucifer/crew#778) as mqucifer/model-performance#1.

    uv run replay sprint-metrics-662
    uv run replay --all                                  # at a time the operator gives
    uv run replay sprint-metrics-662 --model crew-candidate --cap 150
    uv run replay sprint-metrics-567 --arm think-off     # one setting changed

It needs Docker, `gh`, and LiteLLM on :4000 with the builders' key. It runs crew's
own session at the commit `pyproject.toml` pins, so a pin bump re-runs the
baseline (ADR 0004 in mqucifer/project-print). The numbers are in
[`results/`](../results/README.md), and the records stay on the Mac.

- `cases.py`: the five stories, the commit each first attempt started from, and,
  in `cases/`, each story's text as it stood then, from the issue's edit history.
- `replay.py`: one case end to end. It checks out the base in a fresh worktree,
  holds crew's workspace container, runs `crew_org.session` with every call
  through `common.litellm`, and runs crew's gate at `done`. It writes the records
  and the row, and always removes the container and worktree.
- `arms.py`: the arms (mqucifer/model-performance#5), each one setting changed against
  the baseline: an alias, fields in each request, the reasoning sent back, or where the
  session compacts. Its docstring names each arm's request field and value. An arm
  whose setting shows in the answer is checked on every call, and a run where it
  didn't reach the model is `refused` (`arm_not_applied`).
- `spent.py`: what the crew already spent thinking, per role, from crew's event log,
  read-only: observed in production, not an arm.
- `history.py`: the story's real delivery, from crew's event log, read-only, for
  the records.

What moved and what didn't: the experiment's `session.py`, `start.py`, `tools.py`
and `container.py` aren't copied, because crew has since taken them in as
`crew_org.session` and `crew_org.tools.container`. Using those means the harness
needs none of crew's private names.

## Inputs: captured once, never fetched (mqucifer/model-performance#32)

crew's package retention prunes old delivery-history releases (ADR 0021 in
mqucifer/crew). crew-presentation-124's archive went from its release on 2026-10-26.
So a case never fetches a release, or anything else, at run time.

**What's captured:** every case's fetched inputs, once, by sha256, in the records
directory on the Mac, which the nightly backup archives. They're kept as
`records/inputs/blobs/<sha256>`, with `manifest.json` naming each case's inputs and
where each came from.
- The crew-presentation cases fetch a delivery-history archive at their pinned tag,
  and the design-system stylesheet at `v0.1.0`.
- The sprint-metrics cases fetch nothing but PyPI packages. Every case installs
  those under its lockfile's hashes, and PyPI doesn't prune, so they aren't captured.

**crew-presentation-124's archive, recovered:** `delivery-history-2026-10-16-2` was
copied from crew's own build output (its main checkout's gitignored
`var/packages/`). Two pieces of evidence say it's what the case saw:
- that directory holds exactly what crew published: its 10-17 and 10-25 archives
  match their release assets' sha256;
- its 32 files are identical to the extracted copy in crew's clone of
  crew-presentation, the one card 124's delivery ran against.

**At run time** (`inputs.py`):
- **The replay verifies** each of the case's inputs against its hash. A missing or
  changed one refuses the case as `input_missing`, saying which and why: never a
  fetch, never a stand-in.
- **It writes them into the worktree's `.package/`,** as the repository's setup would.
- **The record's `setup:` runs the benchmark's script,** `.benchmark/setup.py`, which
  installs the locked dependencies through the repository's own
  `_sync_dependencies()` and downloads nothing. Only that line of the authored record
  changes, and only for a case with inputs. Both `.package/` and `.benchmark/` are
  kept out of the worktree's git.
- **Each row records** the manifest's sha256 and each input's, so a result is tied to
  exactly what it ran on.
