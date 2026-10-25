# Findings: multilang-404

**Runs:** 2026-09-30, three delivery runs and two design runs. **Code:** crew at
the commit that added it; the full write-up is the crew's
[`experiments/multilang-404/README.md`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/multilang-404/README.md).

## What it showed

- **Run 1: the page was never shown.** The repository view showed only config,
  docs and Python in full, so the page and its tests appeared by name. Every
  answer asked to see them, and QA refused each round, correctly. The fix:
  source in other languages is shown whole.
- **Run 2: passed on the second QA round,** after the harness had reset the
  site between attempts, which delivery doesn't. The harness was changed to
  keep failed work in place.
- **Run 3: passed on the first attempt and the first QA round.** Two edits by
  find-and-replace, the existing test kept working, two new tests, Playwright
  3 of 3, QA accepted both criteria. No asks; 101 s for the Developer.
- **Design:** the first run named an image by tag with no digest, and the flow
  refused it. Since then the Architect names a tag and the flow pins the digest
  from the registry. The second run got the same part and the fixture's digest.

## Limits

One fixture, one story. It shows the loop works, not how often.

## What the record couldn't answer

Nothing was needed from it; the fixture stood in for live work.

## What it suggests

- A harness that differs from what it imitates (here, resetting between
  attempts) changes the result. Keep it the same as the real path, and keep
  each run.
- A model asked for a digest may invent one; read it from the registry instead.

## The Sponsor's conclusion

Not written in this form at the time. What followed: other languages' source is
shown whole, and the design flow pins images itself, both in mqucifer/crew#404.
