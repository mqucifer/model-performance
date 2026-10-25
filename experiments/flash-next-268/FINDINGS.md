# Findings: flash-next-268

**Runs:** 2026-09-28 (the 27B production arm) to 2026-10-01. **Code:** crew at
the commit that added it (mqucifer/crew#422); the full write-up is the crew's
[`experiments/flash-next-268/README.md`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/flash-next-268/README.md).

## What it showed

| Arm | Distinct samples | Usable answers |
|---|---|---|
| 27B, production, `low` | 5 | 1 (4 empty) |
| 27B, `medium` | 5 | 2 (3 empty) |
| 27B, 16-bit KV | 5 | 2 (3 empty) |
| 27B, 8-bit weights | 3 | 0 (3 empty, stopped early) |
| Flash-Next | 6 | 3 (0 empty) |

- **Flash-Next never answered empty,** and generated about twice as fast on
  the 115k prompt: 55 to 65 tokens/s against the 27B's 22 to 35.
- **The early end of turn belongs to the model family, not our serving.** One
  Flash-Next seed stopped cleanly at an arbitrary point, as the 27B does, on a
  different server and weights.
- **Schema-valid isn't crew-valid.** A valid answer listed an existing test
  file as new, which delivery refuses. A trial has to go through apply, the
  sandbox and QA.

## Limits

One request, and the 27B's hardest known one. A fair comparison needs the
crew's ordinary stories too.

## What the record couldn't answer

- **The server's settings for each run** (model, image, KV type, effort) aren't
  in any record. They were noted by hand.
- **The answers** could only be judged from LiteLLM's spend log, by alias and
  time.

## What it suggests

- **TensorFold samples with a fixed default seed.** Identical requests return
  identical output, so use `--seed` or one sample is counted as five.
- **It ignores `response_format`** and a top-level `reasoning_effort`. Effort
  goes in `chat_template_kwargs`.
- Two of its three failures may be fixable at the crew's end: a parser that
  takes JSON from a fence or after prose, and a larger `max_tokens`, which may
  let the run that ran out of budget finish.

## The Sponsor's conclusion

Not recorded here. See mqucifer/crew#422.
