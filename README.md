# model-performance

Measures how the crew's models and the Spark that serves them perform, so the Sponsor can make a few specific decisions. **It answers the questions below and nothing else.** Agreed with the Sponsor on 2026-10-25, after two days of growing threads.

## The questions

| Question | The decision it feeds | What it measures | Issues |
|---|---|---|---|
| **1. How much can the Spark serve at once, and on which serving setup?** | the Spark's session limit (5 for now), and whether a parallel delivery window can work | throughput, latency and lost requests at 4, 6 and 8 sessions, with the answers unchanged | mqucifer/model-performance#7 |
| **2. What does the 27B need to design CAD parts reliably?** | M14: whether training is needed, and for what | pass rate on the 21 hard cases, the baseline against each knowledge arm (skill, references, component library) | mqucifer/model-performance#16 (closed), mqucifer/model-performance#21, mqucifer/model-performance#22, mqucifer/model-performance#23 |
| **3. Is a candidate model better than production, for a crew role or for the window?** | promotion, under ADR 0009 in mqucifer/project-print | the same cases production ran: the benchmark, role-fit, and the window's stories | mqucifer/model-performance#4, mqucifer/model-performance#10 |
| **4. Which session settings help the crew's Developer?** | crew settings, such as compaction | the benchmark's arms | mqucifer/model-performance#5 (closed), mqucifer/crew#906 |

## Candidates
ADR 0009 calls anything that would replace part of production serving a candidate. There are two kinds, judged differently:
- **A candidate serving setup** answers question 1: a different engine (TensorFold instead of SGLang), a newer version of the same engine (SGLang 0.5.22 instead of 0.5.20), or different launch settings. It's judged on throughput and lost requests, with the answers unchanged.
- **A candidate model** answers question 3: different weights, such as a smaller code model for the window, or Qwen3.8-Flash-Next for some roles. It's judged on its answers against production's, on the same cases.

Both are tried at a planned pause with the swap script (mqucifer/model-performance#2), which always restores production, and promoted only on a measured win with no regression.

## The rails
- **A new test runs only if it answers one of these questions.** Anything else gets one parked line, not a run.
- **A question stops when its decision can be made.** Question 2 stops once the arms show whether the CAD failures close; question 1 once the Spark's ceiling is measured.
- **A result is reported as an answer to its question,** in a sentence or two, before any table.
- **No re-measuring a settled setting.** Thinking stays on for every run, since it did better (the Sponsor, 2026-10-25).
- **Quality runs share the Spark; speed runs get it alone.** A quality run's results are pass or fail under a call cap, so they don't depend on load. Each row records `other_calls`.

## From the template

The files every crew-built project starts with (mqucifer/crew ADR 0030). A new
repository is created from this template by `scripts/new-project.sh` in the
crew's repository, and `crew onboard` proposes any of these files a repository
is missing, so older projects catch up when the template changes.

| File | What it does |
|---|---|
| `.github/workflows/checks.yml` | Runs the setup and checks the project's design names (`.crew/project.yaml`) on every pull request, in the design's image, as the crew's sandbox does. Once the project's skeleton makes it green, branch protection requires its `checks` job |
| `.github/crew/run_checks.py` | What `checks.yml` runs. Before the design is merged it has nothing to check and passes |
| `.github/crew/requirements.txt` | Its one dependency, PyYAML, locked with hashes by `uv pip compile --generate-hashes` |
| `.github/workflows/board.yml` | The crew's board automation: card moves no role performs, and an issue a person opens put on the board (a Goal in Inbox (Goals)) |
| `.github/ISSUE_TEMPLATE/goal-template.md` | The Sponsor's form for a new Goal. It arrives labelled `needs:human`, so the crew leaves it alone until the Sponsor swaps that for `goal` |
| `.gitignore` | OS files, caches, and the crew sandbox's own directories |

Nothing here depends on the project's language: that comes from its design. Stories
don't change these files; the template does, by pull request.

## Before the crew takes it over
This repository is a Claude-built alpha, tracked on the Crew roadmap board (https://github.com/orgs/mqucifer/projects/2). Its board workflow (`.github/workflows/board.yml`) runs only by hand, so its issues stay off the crew's delivery board. **At takeover, restore its `issues` and `pull_request` triggers,** as the comment in that file says.
