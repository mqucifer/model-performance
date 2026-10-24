# swap

Runs one command with another model on the Spark, and always brings the 27B
back (mqucifer/model-performance#2, ADR 0004 in mqucifer/project-print).

```
uv run swap <model> --dry-run -- <command>                    # prints every step, changes nothing
uv run swap <model> --engine tensorfold --dry-run -- <command>
uv run swap <model> -- <command>                              # the Sponsor's step: it stops the 27B
```

`<model>` is the candidate's model path, as its engine's launch takes it.
`--engine` names one of `config.toml`'s `[engines]`, `sglang` by default.
Everything after `--` is the command, with its own options untouched.

## Engines

| Engine | For | Its launch in infra | Seed on each request |
|---|---|---|---|
| `sglang` | the 27B, and candidates such as Ornith | `compose/spark/sglang/compose.yaml` | no |
| `tensorfold` | the comparison arm on mqucifer/model-performance#4, such as Nemotron Bolt | `compose/spark/tensorfold/compose.yaml` | yes: it's deterministic without one |

Each engine serves an OpenAI-compatible API on the 27B's port, so LiteLLM's
`SGLANG_BASE_URL` never changes. **The restore always starts the 27B on SGLang**
(`serving.baseline_engine`), whatever the candidate ran on.

## What one run does

| Step | What | Changes the Spark |
|---|---|---|
| preflight | refuse while a `crew tick` runs; ssh answers; the 27B answers through LiteLLM as `crew-local`; LiteLLM lists `crew-candidate` | no |
| swap 1/3 | `docker stop` the 27B's container | yes |
| swap 2/3 | the engine's launch from infra, sent over ssh on stdin, with only the model changed | yes |
| swap 3/3 | the health wait for `crew-candidate` (below) | no |
| run | the command, on the Mac | no |
| restore 1/3 | remove the candidate (`compose down`, else `docker rm -f`) | yes |
| restore 2/3 | bring the 27B back, as `serving.restore` says | yes |
| restore 3/3 | the health wait for `crew-local` | no |

**The restore always runs** once the 27B was touched: after success, a failed
command, a candidate that never answered, a failed stop or start, Ctrl-C,
SIGTERM or SIGHUP. While it runs, those signals are ignored, so a second Ctrl-C
can't stop it half-way. If the 27B doesn't answer afterwards, the swap exits 3
and prints the steps to run by hand.

**Every check goes through LiteLLM on the Mac's :4000.** The config refuses any
other `base_url`, and nothing here knows the engine's port. The candidate serves
on the 27B's port as `crew-candidate`, which LiteLLM's `crew-candidate` alias
points at, so a swap never edits LiteLLM's config.

## The health wait

Nothing makes a request to the engine's port, `/health` included. Each poll:

1. **sends one completion through LiteLLM** (`max_tokens` 1), seeded when the
   engine needs a seed. It's a completion rather than a health endpoint, because
   an engine has answered `/health` with 200 while failing every request
   (mqucifer/model-performance#4). A 200 with choices ends the wait;
2. **otherwise reads the container's state over ssh** with `docker inspect`. A
   container that isn't running ends the wait at once, as a failure, rather
   than at the timeout;
3. otherwise sleeps `poll_s` (20 s) and tries again, up to `ready_timeout_s`
   (20 min).

## What the command is told

The command runs with `SWAP_MODEL`, `SWAP_ENGINE`, `SWAP_ALIAS`
(`crew-candidate`) and `SWAP_SEED_REQUIRED` (`1` for TensorFold) set, so a
harness sends a seed on each request when the engine needs one.

## What infra's launches must take

The swap starts the candidate from its engine's record (mqucifer/infra#40),
setting only the variables that engine lists in `config.toml`:

| Variable | Engines | Unset (the record's own) | A candidate |
|---|---|---|---|
| `MODEL_PATH` | all | its model | `<model>` |
| `SERVED_MODEL_NAME` | all | e.g. `qwen3.8-27b-sglang` | `crew-candidate` |
| `CONTAINER_NAME` | all | e.g. `qwen3.8-27b-sglang` | `spark-candidate`, so it doesn't clash with the stopped 27B |
| `SPECULATIVE_ARGS` | sglang | the 27B's DFlash draft flags, as `${SPECULATIVE_ARGS-...}` | empty: the draft is the 27B's own |

The preflight refuses a launch file that doesn't take its engine's variables,
for the candidate's engine and for SGLang's, which the 27B comes back on.

## Exit codes

The command's own code, or one of the swap's: 2 refused (nothing touched),
3 the 27B didn't come back, 4 the 27B didn't stop or the candidate didn't start
or answer, 130 interrupted. Every ending prints a last line saying which.

## Settings and secrets

`swap/config.toml` holds names only. The Spark's address and ssh user are
`SPARK_ADDR` and `SPARK_USER` in infra's `$INFRA_HOSTS`
(`~/.config/infra/hosts.env`), and the LiteLLM key is `CREW_LLM_API_KEY` in
`~/.config/crew/builders.env`. Both are read with `crew_org.config.load_env`,
never exported or printed: messages name the Spark as `$SPARK_ADDR`.

## Tests

`uv run pytest tests/swap`: every ending above against a fake runner, for an
SGLang candidate and a TensorFold arm, the dry run end to end for both, and the
tick pattern. No test starts ssh, a request or the command.
