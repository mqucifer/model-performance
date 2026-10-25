# Findings: panel-359

**Runs:** 2026-09-29. **Code:** crew at the commits in mqucifer/crew PR 374; the
full write-up is the crew's
[`experiments/panel-359/README.md`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-359/README.md).

## What it showed

| Role | What works | Evidence |
|---|---|---|
| Reviews | Three identical reviews in parallel, findings combined | Random misses: the bind with the rule hidden went 2/5 to 9/10, the base pin 1/5 to 6/10. Both real panels caught all four |
| Developer | Best of three identical attempts, the sandbox picks | 5/12 single runs pass; 3/4 stories get a pass. Focus lines 2/12, both "tests first" |
| Architect | A critic step, not a panel | Same prompt 0/3, lenses 0/3, critics 1/2: the only one of nine proposals to name the bind |

- **Correlated blind spots** are the key finding. Unprompted, `ENTRYPOINT` was
  caught 0/5 by single runs and 0/10 by panels. More samples repeat a shared
  blind spot. Only critique, a written rule or a mechanical check breaks it.
- **Severity varies more than detection.** With the rule shown, the bind was
  raised 5/5 but blocked 0/5.
- **Cost on the Spark:** three at once took 1.0 to 1.65 times one run's wall
  time. KV cache use peaked at 8% with 3 running requests. Generation went from
  about 31 to 57 tokens/s: each request slower, the total higher.

## Limits

One review case, four Developer stories, one design case: direction, not
rates. The review questions were written looking at mqucifer/sprint-metrics#269,
which flatters recall. The base commits were found by time in the event log.

## What the record couldn't answer

- Time to first token per call: the calls don't stream, so the spend log
  doesn't have it, and only the server-wide average over a window does.
- A call's place in its run: the event log had no run id then, so calls were
  matched to arms by time window.

## What it suggests

- **Capacity:** the limits are per-request speed (throughput is shared) and the
  Mac's sandbox (parallel installs and tests), not the KV cache. Per-role
  concurrency should come from load measurements.
- **Tools for next time:** SGLang's `bench_serving` or GuideLLM through the
  proxy, fed with the crew's real prompt sizes from the spend log, for serving
  capacity. Inspect or promptfoo, if quality panels become regular. Check their
  current status first.

## The Sponsor's conclusion

Not written in this form at the time. What followed: the per-role plan went
onto mqucifer/crew#299, and the refinement panel was tested next
([panel-174](../panel-174/)).
