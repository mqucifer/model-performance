# Remove the 100% cap from calculate_escalation_rate

As a **a crew member running the sprint-metrics CLI**, I want **the escalation rate to report the true percentage without a ceiling**, so that **I can see when the crew needed help more than once per completed card**.

## Acceptance criteria

1. **Given** a list of 1 completed card and 2 escalation events
   **When** calculate_escalation_rate is called with that list and escalations=2
   **Then** it returns the integer 200

2. **Given** a list of 10 completed cards and 2 escalation events
   **When** calculate_escalation_rate is called with that list and escalations=2
   **Then** it returns the integer 20

3. **Given** a list of 0 completed cards and 2 escalation events
   **When** calculate_escalation_rate is called with that list and escalations=2
   **Then** it returns the integer 0

4. **Given** a list of 3 completed cards and 1 escalation event
   **When** calculate_escalation_rate is called with that list and escalations=1
   **Then** it returns the integer 33 (round(100/3))

5. **Given** a cards file containing 1 completed card, and the command is run with --escalations 2 --json
   **When** the command completes
   **Then** the JSON object on stdout has "escalation_rate_percent" set to 200 and "flags" has the key "escalation_rate_percent" set to True

<!-- crew:ux-criteria -->
*What the reader sees, added by the UX Designer:*

6. **Given** A cards file containing 1 completed card (created 2024-03-01, started 2024-03-04, completed 2024-03-12), and the command is run with --escalations 2 --sprint-date 2024-03-15 in default table mode
   **When** the command completes and prints to stdout
   **Then** the Escalation rate column in the single data row contains the exact string '200%'

7. **Given** A cards file containing 1 completed card, and the command is run with --escalations 2 --sprint-date 2024-03-15 in default table mode, with no --thresholds file
   **When** the command completes and prints the table to stdout
   **Then** the Escalation rate cell in the data row contains the string '200% ⚠️' because 200 exceeds the default threshold of 10

8. **Given** A cards file containing 1 completed card, and the command is run with --escalations 2 --sprint-date 2024-03-15 --prometheus
   **When** the command completes and prints to stdout
   **Then** the line for the escalation rate metric reads exactly 'sprint_escalation_rate_percent 200'

9. **Given** A cards file containing 1 completed card, and the command is run with --escalations 2 --sprint-date 2024-03-15 --markdown
   **When** the command completes and prints the markdown report to stdout
   **Then** the line reads exactly '- **Escalation rate**: 200% ⚠️ (threshold: 10%)' and the next line reads exactly '  - 2 escalations, 1 completed card'

10. **Given** A cards file containing 0 completed cards (an empty array), and the command is run with --escalations 2 in default table mode
   **When** the command completes and prints to stdout
   **Then** the Escalation rate column in the data row contains the exact string '0%'
**Existing tests** — this story changes what they assert: tests/test_metrics.py::test_calculate_escalation_rate_capped_at_100, tests/test_store.py escalation-rate assertions (R1 assigns them to this epic)

Follows the epic's R1.

**Estimate** — 2 points

---

Split from [mqucifer/sprint-metrics#660](https://github.com/mqucifer/sprint-metrics/issues/660) *(Remove the 100% cap from the escalation rate in the CLI)* by the Business Analyst.