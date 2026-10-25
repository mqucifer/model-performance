# The escalation rate is defined two ways, and can exceed its stated 0-100

<!-- claude -->
**What happens:** the escalation rate is defined two ways, and they disagree once a sprint has more escalations than completed cards.

| Where | What it says |
|---|---|
| `docs/metrics.md`, reference table | "Return the escalation rate as a percentage (0-100)." |
| `docs/metrics.md`, "Escalation count" | Escalated events over throughput, "regardless of whether any card is completed" |
| `docs/formats.md`, Definitions | "Escalations as a percentage of completed cards" |
| `metrics.calculate_escalation_rate` | `round(escalations / completed * 100)`, with no upper bound |

**Found by** the crew seeding the service with its history (mqucifer/crew#280), on v1.2.0, 2026-10-11. `/range` gives Sprint 3 an `escalation_rate_percent` of **200**: two escalated events, and one completed card. The reference table says that can't happen.

The two counts come from different groups. Escalations are every escalated event in the sprint, even on cards that finish in a later sprint or escalate twice. Completed cards are only those finished in the sprint. The story that added the metric, mqucifer/sprint-metrics#10, wanted it to show "how often the crew needs help beyond normal workflow", with 2 escalations over 10 completed cards giving 20%.

**Expected:** one definition of the escalation rate, the same in the reference table, the boundary conditions, `docs/formats.md`, the code and its threshold (10%, `docs/thresholds.md`). A sprint like Sprint 3 then gets a value that definition allows.

## Acceptance criteria

1. **Given** A sprint with 1 completed card and 2 escalations
   **When** calculate_escalation_rate is called with those cards and escalations=2
   **Then** The returned value is 100

2. **Given** A sprint with 10 completed cards and 2 escalations
   **When** calculate_escalation_rate is called with those cards and escalations=2
   **Then** The returned value is 20

3. **Given** A sprint with 0 completed cards and 5 escalations
   **When** calculate_escalation_rate is called with those cards and escalations=5
   **Then** The returned value is 0

**Estimate** — 1 points

---

Triaged as a bug by the Business Analyst: docs/metrics.md reference table states the escalation rate is 'a percentage (0-100)'. The code in src/sprint_metrics/metrics.py::calculate_escalation_rate computes `round(escalations / completed * 100)` with no upper bound. With 2 escalations and 1 completed card the result is 200, which violates the documented 0-100 contract. The existing test (test_calculate_escalation_rate_with_escalations) only exercises 2/10=20%, so it never caught the unbounded case. The code contradicts what the project's own docs accepted.