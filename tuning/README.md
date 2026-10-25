# tuning

How many of the 27B's sessions the Spark carries at once, and with which SGLang
settings (mqucifer/model-performance#7, M12 step 1). Today's crew has never run more
than 4; the target is 6 to 8.

```
uv run concurrent 4                                              # 4 sessions on today's 27B
uv run tune --set mem-fraction-static=0.88 --dry-run -- uv run concurrent 6
uv run tune --set mem-fraction-static=0.88 -- uv run concurrent 6   # restarts SGLang
```

## `tune`: one setting, then the recorded 27B again

Inside the Sponsor's limits, written on mqucifer/model-performance#7 (2026-10-25):

| Limit | How `tune` keeps it |
|---|---|
| this issue's settings only | `--set` takes one of `SETTINGS` (below); anything else is refused |
| from infra's recorded launch, with only that setting changed | the flag's line in infra's `compose/spark/sglang/compose.yaml` is changed, or added after `--port` when the record doesn't set it. Both launches are rendered with `docker compose config` on the Mac and compared flag by flag with infra's own `check_launch.flags`; a launch that differs in anything else, the container's name aside, is refused |
| only when no tick runs | refused while `crew tick` runs, by the swap's pattern |
| the 27B always comes back with `docker start` | refused unless `swap/config.toml`'s `serving.restore` is `container`. The restore is the swap's (`swap.core.restore`): it runs after success, a failed command, a launch that never answered, Ctrl-C, SIGTERM and SIGHUP, and then checks the 27B answers |
| nothing sends a request to SGLang's port | every check is a completion through LiteLLM :4000 as `crew-local`; the container's own state is read with `docker inspect` over ssh |
| every model server in a container | the tuned 27B is the record's image, as container `spark-tuning`, removed after its run |
| each restart recorded | each real run appends its times, setting and exit to `records/tuning/restarts.jsonl` on the Mac, copied to the issue as a comment |

The tuned container keeps the 27B's model, draft and served name, so the crew's
aliases reach it unchanged, and it isn't a candidate: `crew-candidate` isn't used.

| Step | What | Changes the Spark |
|---|---|---|
| preflight | the setting is one of this issue's, and the tuned launch differs in it alone; no tick; ssh answers; the 27B's container is the one running and no `spark-tuning` is there; the 27B answers through LiteLLM; Docker on the Spark renders the tuned launch | no |
| tune 1/3 | `docker stop` the 27B | yes |
| tune 2/3 | the tuned launch on stdin, `docker compose -p spark-tuning -f - up -d` | yes |
| tune 3/3 | the health wait for `crew-local` (the swap's) | no |
| run | the command, with `TUNE_SERVING` set to the setting's short name | no |
| restore | remove `spark-tuning` and check it's gone, `docker start qwen3.8-27b-sglang`, the health wait for `crew-local` | yes |

Exit codes are the swap's: 2 refused, 3 the 27B didn't come back (stop, write it on
#7, message the operator), 4 the tuned 27B didn't stop or start, 130 interrupted.

### The settings

Each with why it's tried, from SGLang's server arguments and hyperparameter-tuning
docs (docs.sglang.ai: "Server Arguments", "Hyperparameter Tuning"):

| `--set` | Record | Why |
|---|---|---|
| `max-running-requests` | 8 | how many requests run at once; only matters once the queue (`sglang_num_queue_reqs`) is above 0 |
| `mem-fraction-static` | 0.80 | the split of memory between weights and KV cache: more KV room, as the tuning doc advises when `token_usage` runs high; start.sh's own defaults were 0.90 and 0.95 |
| `max-mamba-cache-size` | 120 | the 27B is a hybrid model: the radix prefix cache keeps a mamba state per cached prefix, so 8 sessions' turns compete for these slots |
| `mamba-radix-cache-strategy` | extra_buffer | how those states are kept for prefix reuse |
| `schedule-policy` | (fcfs) | `lpm`, longest prefix match, runs queued requests that share a cached prefix first |
| `chunked-prefill-size` | 8192 | smaller chunks stop a long prompt's prefill holding up other sessions' decodes |
| `enable-mixed-chunk` | off | mixes prefill chunks with decodes in one batch |
| `speculative-num-draft-tokens` | 8 | DFlash's draft pays less at higher batch, where the GPU is already busy |

## `concurrent`: N sessions at once

Starts N `replay` sessions together, each its own process, a few seconds apart. The
cases are taken in order and repeated to make N. Each session's workspace is capped at
**1.5 GiB** (`tuning/session.py`, the Sponsor's cap), where crew's sandbox has 2g. That override goes once crew has the setting (mqucifer/crew#821, step 2) and the pin moves.

**Before it starts,** it refuses while a tick runs, and when Docker's free memory
(`docker info`'s total less `docker stats`' use) can't hold N × 1.5 GiB plus 0.5 GiB
in reserve. It prints the ceiling: that's a finding, and nothing else in Docker is
stopped to make room.

**First-time pass** means the crew's gate is green at `done` (the operator,
2026-10-25). The benchmark has no review step, so review isn't measured.

It leaves:

- a benchmark row per session, tagged `sessions`, `serving` and `batch`;
- one row in `results/tuning.jsonl` (`results/README.md` says what each field is);
- on the Mac, under `records/tuning/concurrent/<run>/`: the plan, each session's
  output, and the Spark's raw series from Grafana (`grafana.json`). Grafana keeps 7
  days; this copy is kept.

The Spark's numbers are read from Grafana with infra's read token
(`~/.config/infra/grafana.env`), the series of "3 The Spark under load" plus SGLang's
time to first token. Nothing calls the Spark. A Grafana that can't be read leaves
those fields null, with `grafana` false.

## Tests

`uv run pytest tests/tuning`: every `tune` ending against the swap's fake runner, the
one-flag proof for each setting against infra's launch and checker (copied byte for byte
to `tests/tuning/fixtures/infra/`, from infra cbb7abc), the dry run end to end, and a
concurrent run with fake sessions and Grafana. No test starts ssh, a container, a
session or a request.
