# Findings: analyst-231

**Runs:** 2026-09-30, one run. **Code:** crew at the commit that added it; the
full write-up is the crew's
[`experiments/analyst-231/README.md`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/analyst-231/README.md).

## What it showed

- **The repository part went from 159,310 characters (about 40k tokens) to
  34,091 (about 8.5k),** with no files in full, because the epic names none.
- **It split the epic into 4 stories without asking to see a file.**
- **It wasn't faster:** 368 s, against 307 s with the whole repository. The
  time goes on thinking, not reading. A smaller prompt is safer here, not faster.
- **The other epics, measured without a model call,** came to about 7k to 17k
  tokens of focused context.

## Limits

One epic, one run.

## What the record couldn't answer

Nothing was needed from it.

## What it suggests

Watch whether criteria written from a file seen only by name stay grounded in
its real output. That's for the Code Reviewer and QA on real stories.

## The Sponsor's conclusion

Not written in this form at the time. What followed: refinement splits from the
focused context (mqucifer/crew#231).
