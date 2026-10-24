# swap

Runs one command with another model on the Spark, and always brings the 27B
back (mqucifer/model-performance#2, ADR 0004 in mqucifer/project-print).

```
uv run swap <model> --dry-run -- <command>   # prints every step, changes nothing
uv run swap <model> -- <command>             # the Sponsor's step: it stops the 27B
```

`<model>` is the candidate's model path, as SGLang's `--model-path` has it.
Everything after `--` is the command, with its own options untouched.

## What one run does

| Step | What | Changes the Spark |
|---|---|---|
| preflight | refuse while a `crew tick` runs; ssh answers; the 27B answers through LiteLLM as `crew-local`; LiteLLM lists `crew-candidate` | no |
| swap 1/3 | `docker stop` the 27B's container | yes |
| swap 2/3 | infra's `compose/spark/sglang/compose.yaml`, sent over ssh on stdin, with only the model changed | yes |
| swap 3/3 | poll `crew-candidate` through LiteLLM until it answers, or time out | no |
| run | the command, on the Mac | no |
| restore 1/3 | remove the candidate (`compose down`, else `docker rm -f`) | yes |
| restore 2/3 | bring the 27B back, as `serving.restore` says | yes |
| restore 3/3 | poll `crew-local` through LiteLLM until it answers, or time out | no |

**The restore always runs** once the 27B was touched: after success, a failed
command, a candidate that never answered, a failed stop or start, Ctrl-C,
SIGTERM or SIGHUP. While it runs, those signals are ignored, so a second Ctrl-C
can't stop it half-way. If the 27B doesn't answer afterwards, the swap exits 3
and prints the steps to run by hand.

**Every check goes through LiteLLM on the Mac's :4000.** The config refuses any
other `base_url`, and nothing here knows SGLang's port. The candidate serves on
the 27B's port as `crew-candidate-sglang`, which LiteLLM's `crew-candidate` alias
points at, so a swap never edits LiteLLM's config.

## What infra's launch must take

The swap starts the candidate from infra's record (mqucifer/infra#40), setting:

| Variable | The 27B (unset) | A candidate |
|---|---|---|
| `MODEL_PATH` | its model | `<model>` |
| `SERVED_MODEL_NAME` | `qwen3.8-27b-sglang` | `crew-candidate-sglang` |
| `SPECULATIVE_ARGS` | its DFlash draft flags, as `${SPECULATIVE_ARGS-...}` | empty: the draft is the 27B's own |
| `CONTAINER_NAME` | `qwen3.8-27b-sglang` | `sglang-candidate`, so it doesn't clash with the stopped 27B |

The preflight refuses a launch file that doesn't take all four.

## Exit codes

The command's own code, or one of the swap's: 2 refused (nothing touched),
3 the 27B didn't come back, 4 the candidate didn't stop, start or answer,
130 interrupted. Every ending prints a last line saying which.

## Settings and secrets

`swap/config.toml` holds names only. The Spark's address and ssh user are
`SPARK_ADDR` and `SPARK_USER` in infra's `$INFRA_HOSTS`
(`~/.config/infra/hosts.env`), and the LiteLLM key is `CREW_LLM_API_KEY` in
`~/.config/crew/builders.env`. Both are read with `crew_org.config.load_env`,
never exported or printed: messages name the Spark as `$SPARK_ADDR`.

## Tests

`uv run pytest tests/swap`: every ending above against a fake runner, the dry
run end to end, and the tick pattern. No test starts ssh, a request or the
command.
