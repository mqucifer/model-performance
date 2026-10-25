# The CAD-code evaluation

Can the crew's model write CadQuery for a part from a spec, and how reliably does it
call its tools while it does? North Star D2, as mqucifer/model-performance#3.

    cad_eval/image/build.sh                    # once: the CadQuery image, on the Mac
    uv run cad-eval --first                    # one part per tier: the first run
    uv run cad-eval spacer box-lid --cap 20
    uv run cad-eval --all --model crew-candidate   # at a time the operator gives

It needs Docker, the image, and LiteLLM on :4000 with the builders' key. It refuses
to start while a `crew tick` runs. A part may make `--cap` calls (20), and the run
`--total` (100). The numbers are in [`results/`](../results/README.md), and the
records stay on the Mac, in `records/cad_eval/<part>/<run>/`: `events.jsonl` (every
call and tool call, with their text), `files/` (what the model wrote), `checks.json`
and `result.json`.

- `parts.py` and `parts/*.md`: the parts, each a spec as a person would write it
  (purpose, dimensions, tolerances, placement) and its checks as data. They're
  written here, from scratch, modelled on functional printed parts, in five tiers
  after the CAD-code benchmarks' simple-to-complex split (CADPrompt, Text2CAD): one
  primitive with features, several features, shells and patterns, sweeps, and a
  fit to a mating part.
- `measure.py`: measures a STEP file **in the container only**, sent on stdin and
  run with `python -I`, so the session can neither change it nor shadow its imports.
  It reports validity, solids, bounding box, volume, the mesh's closedness (trimesh,
  at 0.01 mm), whether named points are inside the material, and the overlap with a
  mating part.
- `checks.py`: those measures against the part's spec, on the host. Each part's
  reference solution in `tests/cad_eval/reference/` passes every check, and a
  planted wrong one in `tests/cad_eval/wrong/` fails, on real CadQuery in the image.
- `tools.py`: `write`, `run`, `inspect`, `done` and `blocked`, over the part's
  directory, and how each call is judged (below).
- `session.py`: the conversation, a call at a time through `common.litellm`, until
  `done`, `blocked`, or a stop.
- `run.py`: one part end to end, and the CLI.
- `container.py` and `image/`: crew's own `Held` and `Sandbox` at the pinned commit
  (no network, read-only image, the invoking user, capped resources), with a
  CadQuery 2.8.0 image whose every package is frozen in `image/requirements.txt`.
  Generated code runs only there.

## Tool-calling reliability, in BFCL's categories

Each tool call is judged as it's made, following the Berkeley Function Calling
Leaderboard (v3)'s split between the call's form (AST) and what it does (executable):

| Outcome | What it means |
|---|---|
| `malformed` | crew's own argument rule (`check_arguments`) refuses it: not a JSON object, no such tool, or an unknown or missing argument. The benchmark's meaning exactly, so `malformed_tool_calls` compares across suites |
| `ill_typed` | well formed by crew's rule, but a value of the wrong type: BFCL's type check |
| `failed` | well formed, but the tool couldn't do what it asked: a path outside the part's directory, a file that isn't there, or content over the limit |
| `ok` | it did what it asked |

**A script that runs and raises is `ok`:** the tool did what it was asked, and the
CAD code failed, which `compiles` counts. `tool_reliability` is `ok` over all tool
calls in the run. Every judgement is told back to the model, as the crew's session
does.

## A part is right when

- **it compiles:** the script named at `done` runs again from a clean start, exits
  0, and writes `part.step`, which loads as a valid shape with at least one solid;
- **its mesh is closed:** watertight, with a consistent winding, a volume;
- **it's within tolerance:** one solid, the bounding box within the spec's tolerance
  (which fixes its placement too), the volume within 2%, each feature's points in or
  out of the material, and for a fit, no overlap with the mating part.

A spec states each dimension's tolerance; points sit at the tolerance's edges where
a diameter or a clearance is the feature (the spacer's bore, the lid's lip).
