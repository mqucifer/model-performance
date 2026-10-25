# Findings: model-fit-29

**Runs:** the 27B baseline, round 1: `results/role_fit.jsonl`, runs `20261025T184232Z-s1` to `20261025T210828Z-s1`, 2026-10-25. **Code:** model-performance `role_fit/` (mqucifer/model-performance#10); crew 099879f. Rounds 2 and 3 and the candidates are still to run.

## What it showed

So far, only the incumbent's first round has run: one call on each of 26 E1 requests (18 execution, 8 judgement).

- **Qwen3.8-27B answers E1's requests in their form 24 times in 26.** On the same requests, production's own answers held their form 22 times, and crew accepted 20 of them.
- **No empty, runaway or cut answer in 26.** Production had one empty answer among these requests.
- **Both failures are the Developer's two-part answers** (2 of 10). Each field named its block `@@b1` or `@@b1@@` instead of `b1`, the mistake crew refused in production.
- **Judgement roles: 8 of 8 valid.**

There's no candidate yet, so the decision rule hasn't been applied.

## Limits

- **One round:** the incumbent's spread, which the decision rule needs, comes from rounds 2 and 3. A single criteria check thought 4.4 times longer than production did on the same request.
- **Load:** 17 of 26 calls shared the Spark with m14-hard-eval's CAD run (4 sessions). Times are read beside `other_calls`; validity doesn't depend on load.
- **Dated prompts:** 23 of 26 requests asked for a form the pinned crew no longer asks for. That covers the Developer's two-part answer, which was retired, and schemas that have changed since. Only the 3 criteria checks are current.
- **The scorer checks the form,** not the step's own rules. On production's answers it matched crew's verdict 24 times in 26.
- **Not measured yet:** the Developer's sandbox pass rate (a dated answer has no crew left to apply it), QA's agreement with what happened, and the hedge logit-bias arm.

## What the record couldn't answer

- **E1's prompts survive only in LiteLLM's spend log,** which keeps 90 days. These were copied to the records directory on 2026-10-25. Any later case must be copied before 2027-01.
- **sprint-metrics#567's own Developer calls** ran before crew#633, outside E1's window.

## What it suggests

- **Bring E1's prompts forward to the crew's current steps** before the candidates run, or take cases from a current window, so the Developer's results aren't dated.
- **A check in crew's two-part parser** that accepts `@@bN@@` as `bN` would have saved one of production's refusals. It's moot now that the form is retired.

## The Sponsor's conclusion

_Left for the Sponsor._
