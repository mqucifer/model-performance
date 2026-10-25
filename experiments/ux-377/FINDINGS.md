# Findings: ux-377

**Runs:** 2026-09-30, one run. **Code:** crew at the commit that added it; the
full write-up is the crew's
[`experiments/ux-377/README.md`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/ux-377/README.md).

## What it showed

- **4 stories, 2 criteria each,** with no coverage problems and nothing beyond
  reach. Split in 307 s, note in 206 s.
- **Every criterion asserts something a test can check in the output:** an
  exact line, what comes before what, which lines appear and which don't.
- **The note read the code it's about** and used the real thresholds.

## Limits

One epic, one run.

## What the record couldn't answer

Nothing was needed from it.

## What it suggests

The note's sample output wasn't consistent with itself, though the criteria
were. Nothing checks the sample against the criteria; it's evidence to watch.

## The Sponsor's conclusion

Not written in this form at the time. What followed: the UX Designer role
(mqucifer/crew#377).
