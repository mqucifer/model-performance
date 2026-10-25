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
