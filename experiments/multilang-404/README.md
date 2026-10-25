# Can the crew deliver a project that isn't Python, end to end?

**From:** mqucifer/crew#404, phase 2c, before infra had Goals.
**Ran:** 2026-09-30, read-only, through LiteLLM on the Spark.
**Status:** concluded. A worked example; see [worked-examples.md](../worked-examples.md).
**Harness:** in mqucifer/crew, [`experiments/multilang-404/`](https://github.com/mqucifer/crew/tree/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/multilang-404) at 39e9865.

## The question

Does a part in another language go through the same delivery loop as Python?
That's the Developer's answer applied, its named tests found, the project's
checks run in the sandbox, and QA judging the story. Separately, does the
Architect propose the right part for such a project from its code alone?

## Method

- **A fixture, not live work:** the crew's `tests/fixtures/static-site`, a
  static HTML page with Playwright tests and one `javascript` part, copied to a
  temporary folder for each run.
- **The story:** add a "Changed: …" line to the page's health section, after
  the status and before the next section.
- **Delivery:** the Developer's answer through the model, applied, its tests
  checked to be in their files, the checks run in the sandbox on the Playwright
  image, then QA. A refusal goes back to the Developer with its reasons.
- **Design:** a fresh design of the same site, with its recorded design
  removed, checked for a `javascript` part with Playwright's test files and an
  image pinned to a real digest.
- **Each run was kept,** and the harness was fixed between runs where it
  differed from delivery.

## What it reads

Nothing from the crew's record. The fixture and the crew's own delivery and
design code only.

## Harness

| File | Does |
|---|---|
| [`run.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/multilang-404/run.py) | The delivery loop on a temporary copy of the fixture: the Developer's answer, apply, the test-name check, the sandbox, QA |
| [`design.py`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/multilang-404/design.py) | The Architect's design of the fixture from its code, and the image pin check |

## How to run it

1. **Before:** the crew is idle; LiteLLM and the model are up; the sandbox can
   pull the Playwright image.
2. **Run,** from the crew checkout's root:
   ```
   uv run python experiments/multilang-404/run.py
   uv run python experiments/multilang-404/design.py
   ```
3. **Results:** `result.json`, `design-result.json` and a log, beside the
   harness. Under infra's rules, they'd go to `$INFRA_RESULTS/multilang-404/<run-id>/`.

## What it changes

Nothing. A temporary copy, nothing posted.
