# Findings: panel-174

**Runs:** 2026-10-02 (108 calls, none failed); replays on 2026-10-05 and
2026-10-08 (12 calls each). **Code:** crew at the commits that added each arm;
the full write-up is the crew's
[`experiments/panel-174/README.md`](https://github.com/mqucifer/crew/blob/39e98659cd08fcd595d63c36259b20a74f864be9/experiments/panel-174/README.md).

## What it showed

- **The panel was worth building,** in parallel, with changes. Before the
  split it reliably named the problems between epics (findings 7 and 8, in 7 of
  9 runs) and rarely added an unneeded note (8 of 269, 3%).
- **It missed four of the ten findings in every run, together:** environments,
  a version rule it quoted but didn't apply, what to instrument, and a counting
  rule whose decision never named the Goal.
- **The decisions in context carried a finding:** with the Sponsor's decision
  in front of them, the serial panel named Postgres 3/3; without it, 0/3.
- **Parallel costs nothing in quality,** and the four calls on an epic took
  313 s of wall time against 810 s serial. Each request was slower (median 252 s
  against 193 s), while the Spark delivered 81 tokens/s against 29.
- **Most of what it raises is design:** about 70% of the needed notes were for
  the Architect to settle, 25% for the Product Owner, none for the Sponsor.
- **The replays:** the crew's own panel code removed the unneeded notes (0 of
  27). Adding the project's decision log found two more findings, each citing
  its log entry. One finding was still missed with its decision in front of
  every member: a role's miss, not a missing source.

## Limits

One reader scored every note, against a written rule. Three runs per arm, and
one run per replay: direction, not rates. The arms differ by one or two
findings, within the run-to-run spread.

## What the record couldn't answer

- **Decisions that don't name their Goal** can't be found by a rule. Two of the
  four sources the design expected were invisible to it.
- **Per-call model time** came from the spend log by each call's time window.

## What it suggests

Recorded at the time:
- record the Sponsor's decisions where a rule finds them;
- give each member a check for its blind spot, not only a lens;
- keep each member on its own epic.

The 2026-10-05 replay, read after ADR 0017, moved the production half of the
environments finding to infra.

## The Sponsor's conclusion

Not written in this form at the time. What followed: the panel was built
(mqucifer/crew#440), the project's decision log was added to its context
(mqucifer/crew#468), and the "For infra" notes became infra's carry-in list
(mqucifer/crew#475).
