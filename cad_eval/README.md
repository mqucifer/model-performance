# The CAD-code evaluation

Can the crew's model write CadQuery for a part from a spec, and how reliably does it
call its tools while it does? North Star D2, as mqucifer/model-performance#3.

    cad_eval/image/build.sh                    # once: the CadQuery image, on the Mac
    uv run cad-eval --first                    # one part per tier: the first run
    uv run cad-eval spacer box-lid --cap 40
    uv run cad-eval --all --model crew-candidate   # at a time the operator gives
    uv run cad-eval --hard-first --cap 20       # the harder cases' first five
    uv run cad-eval --hard                      # all 21 harder cases, at a time the operator gives

It needs Docker, the image, and LiteLLM on :4000 with the builders' key. It refuses
to start while a `crew tick` runs. A part may make `--cap` calls (40), and the run
`--total` (by default, the cap for each part it runs). The numbers are in [`results/`](../results/README.md), and the
records stay on the Mac, in `records/cad_eval/<part>/<run>/`: `events.jsonl` (every
call and tool call, with their text), `files/` (what the model wrote), `checks.json`
and `result.json`.

- `parts.py` and `parts/*.md`: the parts, each a spec as a person would write it
  (purpose, dimensions, tolerances, placement) and its checks as data. They're
  written here, from scratch, modelled on functional printed parts: 30 parts, six in
  each of five tiers after the CAD-code benchmarks' simple-to-complex split
  (CADPrompt, Text2CAD):
  1. one primitive with features: spacer, washer, mounting plate, hex standoff, end
     cap, slotted bar;
  2. several features: L-bracket, flanged bushing, motor plate, stepped shaft,
     U-channel, counterbored block;
  3. shells and patterns: vented box, pegboard plate, cup, bolt flange, heat sink,
     divided tray;
  4. sweeps, lofts and revolves: hose elbow, funnel, tapered foot, coil spring,
     pulley, drawer handle;
  5. a fit to a mating part: box lid, shaft collar, bearing housing, rail slider,
     hole plug, tube coupler.
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
  0, and writes `part.step`, which loads as a valid shape with at least one solid.
  CadQuery 2.8's `cq.exporters.export` writes a shelled solid (an open box, a cup) as
  its bare closed shell, so a closed shell is made a solid first, as a slicer fills
  it, and `checks.json` says so (`solids_from_shells`). An open shell stays no solid;
- **its mesh is closed:** watertight, with a consistent winding, a volume;
- **it's within tolerance:** one solid, the bounding box within the spec's tolerance
  (which fixes its placement too), the volume within 2%, each feature's points in or
  out of the material, and for a fit, no overlap with the mating part.

A spec states each dimension's tolerance; points sit at the tolerance's edges where
a diameter or a clearance is the feature (the spacer's bore, the lid's lip).

## The harder cases (mqucifer/model-performance#16)

**Every CAD run uses `crew-code-think`, with thinking on**, and each row names it in
`model_alias`. That's the Sponsor's decision of 2026-10-25: "We've seen thinking on do
better. Let's spend time on new tests, not rehashing." So M14's arms have no
thinking-off arm.

M14's first step: find where the base model breaks. On the 30 parts the 27B passed
28, so `cases.py` pushes past them in three kinds, each a tier after the five above.
A case runs in the same session, tools and container as a part. It is checked the
same way (`compiles`, `closed_mesh`, `within_tolerance`), and its row goes in the same
`results/cad_eval.jsonl`, with five fields of its own (`results/README.md`). A case
may have several **members**, each its own STEP file, which its one script writes. The
case's prompt (`session.system_for`) and its `done` name those files, a one-part
case's `part.step` too. The 30 parts' prompt, tools and rows are unchanged.

| Tier, kind | Cases | Where they come from |
|---|---|---|
| 6, `tight` | `living-hinge`, `press-fit-pin`, `snap-hook`, `dovetail-slider`, `print-in-place-hinge`, `spur-gear`, `m8-bolt` | Features of printed parts whose tolerance is the point. The hinge web's 0.4 mm is the living-hinge design guides' range for thin flexures (Protolabs, Formlabs). The press fit's 0.1 mm diametral interference is common FDM practice. The snap hook's proportions are Bayer's "Snap-Fit Joints for Plastics" cantilever (1.42% strain). The gear is a standard involute, module 1.5, 20°. The bolt is ISO 68-1's basic M8 × 1.25 profile |
| 7, `assembly` | `pin-clevis`, `shaft-bushing-collar`, `drawer-cabinet`, `gear-pair`, `bolt-nut`, `snap-enclosure`, `caster-wheel` | Two to five printed parts that must fit, placed as assembled: a clevis joint, a shaft in a bushing held by a collar, a drawer, a gear train with backlash, a nut on a bolt, a snap-shut box, a five-part caster |
| 8, `worded` | `shelf-bracket`, `tube-clip`, `d-shaft-knob`, `wall-hook`, `cable-comb`, `spool-holder`, `pi5-nvme-case` | Asked for as a person would, the dimensions left to the model: a frame to check it in, and what it must do ("holds a 2 kg shelf"). `pi5-nvme-case` is the Sponsor's (2026-10-25), below |

**What's checked, as data per member** (`cases.Member`, compared in `checks.member`):
- **dimensions:** a bounding box within a tolerance, or bounds (`within`, `spans`); a
  volume or a volume range; and points in or out of the material, at a tolerance's
  edges.
- **samples:** points along a line, round a circle or along a helix, with how many of
  them are inside, how often they change from in to out, and how wide each gap is:
  - an involute's tooth width at two radii, a prime count of points so they can't
    line up with the teeth;
  - a thread's pitch, crests and roots, and its hand (along a right-hand helix a
    right-hand thread hardly changes at all);
  - a comb's six 5 to 6 mm slots;
  - a port's line of sight out through a wall.
- **holes:** cylindrical hole faces along an axis, of a radius in range, wherever
  they are: screw holes in a worded part.
- **fits:** each `Gap` with a mating part the case gives or another member, names its
  expected **interference** (the overlap's volume) and, for a clearance, its
  **distance** (the closest the two come). A press fit must overlap (0.08 to 0.12 mm
  diametral: 5.9 to 9.2 mm³); a clearance fit mustn't (at most 0.01 mm³), with its gap
  in the spec's range. A print-in-place joint's own solids are checked the same way.
- **vents:** lines cast through a lid on a 3 mm grid, the open ones' area.
- **the load check, a simplification:** see below.

Each case's reference solution in `tests/cad_eval/reference/` passes every check, and
a planted wrong one in `tests/cad_eval/wrong/` fails at least one, on real CadQuery
in the image (`test_cases_in_image.py`). The wrong ones are the mistakes each case is
there to catch: a web too thick, a pin with no interference, a hook that overlaps its
ledge, a rectangular groove, a pin bore too tight, straight-flanked teeth, a
left-hand thread, holes too tight, parts touching, gears tooth on tooth, threads with
no clearance, hooks that don't reach their windows, a thin arm, a round bore, a missing
slot, a spindle too big for the spool, and a Pi case with no room for the Base.

### The load check is a simplification

`Load` checks the bending stress at one section: σ = M·c/I.
- **The section:** the material in a stated plane, measured in the container (its
  area, centroid and second moments).
- **The moment:** M is the stated load times its arm.
- **The stress terms:** I is the section's second moment across the load, and c the
  farthest material from its centroid along the load.
- **The limit:** it passes at no more than **13.1 MPa**: PLA's yield strength over a
  safety factor of 4.
  - **PLA's strength:** 52.5 MPa, printed flat (XY), ASTM D3039, from Ultimaker
    PLA's technical data sheet v5.00. Printed upright (Z) the sheet shows no yield,
    and PLA breaks lower across its layers.
  - **The factor:** it covers that, the infill, and creep under a standing load.

| Case | Section | Load | Arm |
|---|---|---|---|
| `shelf-bracket` | X = 20 mm | 2 kg on two brackets: 9.81 N on each | to the shelf's middle, 75 mm out: 55 mm |
| `wall-hook` | X = 8 mm | 5 kg: 49.05 N | to the hook's far end, the worst place it could hang |
| `spool-holder` | X = 8 mm | 1 kg: 9.81 N | to the spindle's far end |

It ignores the screws, shear, the stress raised at corners, and the layers'
direction. So it says only that a section isn't far too thin, never that a part is
strong enough. A row's `load_ok` is this check alone.

### The Sponsor's case: a Raspberry Pi 5 with a Pimoroni NVMe Base Duo

`pi5-nvme-case` is a base and a lid round a Pi 5 with an NVMe Base Duo under it,
carrying two 2280 SSDs (mqucifer/model-performance#16's comment of 2026-10-25). Its
checks hold only what the boards' drawings publish:

- **Raspberry Pi 5:** Raspberry Pi Ltd's "Raspberry Pi 5" mechanical drawing
  (datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf, also p. 3
  of the product brief):
  - the board, 85 × 56 mm;
  - its holes, Ø2.7 on a 58 × 49 mm rectangle, 3.5 mm in;
  - USB-C at 11.2 mm and the micro HDMIs at 25.8 and 39.2 mm along the long edge,
    their tops 3.2 and 3.4 mm above the board;
  - Ethernet at 10.2 mm and the USBs at 29.1 and 47 mm along the short edge, 3 mm
    past it;
  - nothing else on top dimensioned taller than 4.4 mm.
- **NVMe Base Duo:** Pimoroni's drawing on its product page (nvme-base-duo-drawing.png):
  - 87.60 mm long, its holes 4.50 mm from its flex cable's edge and 3.50 mm from its
    bottom edge, on the Pi's pattern;
  - its flex connector at 29.89 mm;
  - M.2 connectors 6.7 mm tall.
  
  The kit's contents, on the same page: 12 mm M2.5 standoffs under the Pi and 5 mm
  standoffs for the SSDs. DigiKey's getting-started guide says the SSDs sit on the
  Base's top, under the Pi.
- **What's checked:**
  - the Pi kept out, 0.5 mm clear, from 13 mm under its top to 4.4 mm above it, with
    columns left at its holes;
  - the Base kept out, 0.5 mm clear, along its published 87.6 mm and from its bottom
    edge to its far holes' line;
  - a clear line of sight out of each published port, at half its published height
    for USB-C and HDMI, and 1 mm above the board for Ethernet and USB;
  - a boss under each hole, below the Base;
  - room for the flex cable round the Base's edge, on its connector's centre line;
  - at least 300 mm² of vents through the lid over the boards (the evaluation's own
    threshold: nothing published sets one);
  - a lid that's a separate part, not overlapping the base.
- **Not checked, because neither maker publishes it** (left out rather than guessed):
  - either board's thickness, so the stack's heights are kept out only where no
    thickness could put a board;
  - the Base's size along Y;
  - the Ethernet and USB sockets' heights;
  - the microSD slot's place;
  - the PCIe connector's place on the Pi;
  - the flex cable's width;
  - the parts under the Base;
  - a printable wall thickness, and whether the lid's catch holds.

  Where a check would need one of these, the case leaves it out. Tom's Hardware's
  review gives 85 × 56 mm for the Base, which disagrees with Pimoroni's 87.60, so it
  isn't used.

## Whose a failure is

A harder case's row says whose its failure is (`fault`):

| `fault` | When |
|---|---|
| `model` | It reached `done` with a wrong design or a script that failed, or it gave up: no tool call, the backstop, or its own `blocked` |
| `tool` | The evaluation's own tools failed it: a measure that didn't finish or couldn't measure a shape that loads, or the run crashed |
| `infra` | Nothing about the case: the container or the image, a failed call to LiteLLM or the Spark |
| `budget` | The call cap ended it before an answer: no verdict on the design |
| null | It passed every check |

A `blocked` the model says is counted the model's. Its reason, in the records, is read
by hand in the write-up, since a missing tool may be what it names.

## The arms (M14, mqucifer/model-performance#21)

An arm gives the session something more than the baseline and runs the 21 harder
cases with it, each row naming its `arm` (null for the baseline). They run separately,
so each says which lever helped.

    uv run cad-eval --hard --parallel 4                 # the baseline
    uv run cad-eval --hard --arm skill --parallel 4     # the CadQuery skill and lookup
    uv run cad-eval --hard --arm refs --parallel 4      # the engineering references alone
    uv run cad-eval --hard --arm skill-refs --parallel 4  # both

**`skill`: the CadQuery skill and a signature lookup.**
- **The skill** is in the crew's own shape (crew's `session/skills.py`, crew#839).
  - The start names each skill in one line, crew's `start_line`, after the case's
    spec.
  - The session reads one with a `skill` tool, crew's `SKILL_SPEC` word for word.
  - The text, `skills/cadquery/SKILL.md` and five `references/*.md` in the Agent Skills
    layout, is one skill per file, so a topic is read only when needed. It covers how
    to build a part (sketch, then features, then checks), and references for:
    - sketch and extrude;
    - selectors;
    - threads and helices;
    - assemblies and fits;
    - errors.
  - It's distilled from CadQuery's documentation for 2.8.0, the version the image
    pins, and each file links its pages.
  - `test_skills_in_image.py` checks every CadQuery name it mentions exists in the
    installed library, so it can't drift from what the session runs.
  - **Crew's mechanism, crew's code:** only the registry is here (`cad_eval/skills.py`).
    Crew's `SKILLS` holds only crew's own skills. Letting it take skills from outside
    would be a later crew change.
- **`lookup`** (`lookup.py`) runs in the container, from stdin with `python -I`, as
  the measure does.
  - A name or a fragment goes in. Out come the matching names in the installed
    CadQuery, with their signatures and docstrings' first paragraphs, at most 20.
  - `OCP.<module>` lists that module's classes.
  - Its calls are judged in the same categories as every other tool's.

**`refs` and `skill-refs`: engineering references** (mqucifer/model-performance#22).
- `skills/references/`: a `SKILL.md` index (which table answers which question) and
  three tables, each a skill of its own, read with the same `skill` tool:
  - `ref-fasteners`: ISO 273 clearance holes, ISO 262 pitches and tap drills, ISO
    4032 hex nuts, and a wood screw's clearance (practice);
  - `ref-fits`: the ISO 286 hole-basis fits and their deviations;
  - `ref-fdm`: what a printed part needs to fit. That's clearances, holes printing
    undersize, heat-set insert holes and minimum walls, all marked practice, not a
    standard. Supports and orientation stay out: printability is a second pass.
- They're values, not procedures: the skill arm's fit-checking advice cost calls.
- Every row names its source, and the sources are listed at the foot of each file.
- ISO standards are cited by number. Their text isn't reproduced: the values come
  from free reproductions that were checked against each other, and where they
  disagree both are given.
- `test_references.py` fails a row without a source. It also checks that ISO 273's
  M4 holes fall inside the cases' screw-hole checks, since both come from the
  standard.
- `refs` offers the references alone, with no CadQuery skill and no `lookup`.
  `skill-refs` offers both sets and `lookup`. So each lever shows on its own.

**Running cases at once (the Sponsor, 2026-10-25: these runs test correctness, not speed):**
- `--parallel N` runs N cases at once: at most what the operator gives, and refused
  above what Docker's free memory holds.
  - The memory check is Docker's total less what its containers use and a 1 GiB
    reserve, over the sandbox's 2 GiB cap per container.
  - The Spark takes 6 sessions at once in all, across ticks, builders and proof runs.
- Each row records its `concurrency`, and its `other_calls` from LiteLLM's spend log.
- A case's calls are capped by count, never by time, so its result doesn't depend on
  the load. **No timing claims are made from these runs.**
- `touch <work dir>/cad_eval.stop` stops a run from starting more cases, and the ones
  running finish. That's for the operator, when another builder needs the Spark to
  itself.

**`calls_to_first_compile`**, on every case's row: the call after which a `run` first
exited 0 with every output file written. That's the turns spent before a first
compiling part.

## Runaways: a call that thinks to the token limit

**What happened, 2026-10-25.**
- bolt-nut's first call in the baseline thought towards the Developer's
  65,536-token limit.
- Under that evening's load SGLang wrote about 20 tokens a second per session, so a
  call that long takes about an hour. The client's one-hour timeout ended it first, at
  20:50Z.
- It was first read as an unanswered call (`infra`). The operator traced it in
  LiteLLM's log: SGLang was still generating, and aborted when LiteLLM disconnected.

**Today's 748 CAD calls, profiled** (before the change below):
- The longest that succeeded wrote 44,843 completion tokens, 43,346 of them reasoning.
  The next were 36,396 (34,583 reasoning) and 35,010 (34,579).
- Their content was at most a few hundred characters, and each ended in a tool call.
- So these runaways are thinking that doesn't close, not the whitespace crew's cut
  catches.

**Production parity** (the Sponsor's choice, 2026-10-25):
- A harder case's calls are streamed (`send.py`: role-fit's sender, with tool calls
  assembled from their pieces). A streamed call's reads keep coming, so the timeout
  no longer ends it, and the records hold what it wrote.
- Crew's own cut is the only cut: the content running on as whitespace past
  `RUNAWAY_CHARS`.
- No thinking budget is added. The Sponsor's earlier ruling is that a budget hides
  the real problem, the context and the tools.
- A call that thinks to the limit ends as `length`, costs its call, and the session
  goes on as production's does.
- The row counts such calls (`runaways`) and the reasoning and content tokens they
  reached. A runaway is the model's.
- How many runaways each arm has is a finding of its own: a knowledge arm that
  shortens the thinking shows it there.

**Rows before the change:** bolt-nut's baseline runaway was a call timeout. It's
re-marked from that evidence: `runaways` 1, the model's, with the tokens unknown
(null). bolt-nut's rerun stays `budget`. It ended on the backstop after 20 completed
calls, none of them a runaway.

**Longer first thoughts with the skill.** In the skill arm, two calls taken for
runaways weren't: they finished, with tool calls, inside the hour.
- gear-pair's second call wrote 54,309 tokens, and bolt-nut's 62,218, close to the
  limit.
- Both came straight after reading the skill, and both are longer than anything in
  the 748 calls before.

## The spread of repeated runs (mqucifer/model-performance#27)

One run per case can't tell a gap from noise where runs vary most. So the four gear
and thread cases (spur-gear, m8-bolt, gear-pair, bolt-nut) run several times in each
of the four arms: the baseline, `skill`, `refs` and `skill-refs`.

    uv run cad-eval spur-gear m8-bolt --repeat 2 --arm refs --parallel 4 --cap 20
    uv run python -m cad_eval.spread --measure-capped   # then the report

- **Samples:** `--repeat N` runs each named case N times. Each run is its own row and
  records, and the row's `sample` says which.
- **The report:** `spread.py` builds it from the rows. For each case in each arm (a
  cell):
  - its passes out of n, with a 95% Wilson interval;
  - each check's pass rate;
  - where each run ended, and its first failing check;
  - the call of its first compiling part.
- **The runs still needed:** the report lists them for each cell.
- **What counts as a sample:** a harness or infrastructure fault (`tool`, `infra`)
  isn't one.
- **A capped run doesn't finish in 20 calls**, which isn't "can't".
  `--measure-capped` measures its last files in the container, offline, so its
  checks show where it had got to.

**The rule, set before the runs** (the operator, 2026-10-26). Sampling is staged to
save the Spark: three runs per cell first, counting runs already made. **n = 3 is a
screen, not a measurement.**
- **A cell** fails at 0 of 3 (or at most 1 of 5) and passes at 3 of 3 (or at least
  4 of 5). Otherwise it's open.
- **A case** is a **gap** if every arm's cell fails: a candidate for training or a
  tool. It's **closed** if any arm's cell passes. Anything else is **noise**.
- **A noisy case** gets two more runs only where they could change its verdict:
  - a cell at 2 of 3;
  - or a cell at 1 of 3, when every other cell fails or is at 1 of 3.

## What a run keeps (mqucifer/model-performance#40, V4)

**Every request, exactly.** Before each call the session keeps a `request` event in
`events.jsonl` with what's new since the last one: the messages added, and the tools
and parameters when they change (the body as it went over the wire, streaming flags
and alias included). When it changes an earlier message, it keeps a `rewrite` event.
`transcript.rebuild(events, n)` replays them into call `n`'s body, and a test holds
every call of a run to it. Full requests aren't stored: they repeat their prefix.

**Each call** records when it started, how long it took, and the model its response
named (`served_model`).

**Each row names what it ran on, read rather than typed** (`identity.py`):
- **The harness:** `harness_commit`. `cad-eval` refuses to run with uncommitted
  changes to tracked files, so `harness_dirty` is false on every row it writes.
- **The texts:** `skills_sha`, one sha256 over every skill and reference file.
- **The image and library:** `image_id` (the image's digest), and `cadquery_version`
  and `ocp_version`, read in the run's own container.
- **The serving:** infra's record of what production runs
  (`inventory/services/sglang.yaml` at infra's main): `serving_infra_commit`,
  `serving_image` (also `serving`), `serving_digest` and `serving_model`. It's read as
  the batch starts and again as each run ends, and `serving_record_changed` flags a
  difference. Each call's response model gives `served_model` (the first),
  `served_models` (how many there were) and `served_changed`. The full list is in
  `result.json`.
- **A failed call** keeps its HTTP status in `result.json` (`said.status`), never the
  body, which can echo the request.

The typed `--serving` flag is gone.

## The v2 image (mqucifer/model-performance#40)

`model-performance/cadquery:2.8.0-v2`, from `image/Dockerfile.v2` by `image/build.sh v2`:
- **The base:** the CadQuery image, `model-performance/cadquery:2.8.0`. `build.sh`
  refuses unless that tag is the pinned id (`1f29a53a…`, the image v1 ran on).
  BuildKit can't take a local image by digest in `FROM`, so the script checks it,
  and the image records it as the label `org.opencontainers.image.base.id`.
- **One package added:** `libosmesa6=22.3.6-1+deb12u2`, so VTK renders offscreen for
  `view`. It comes from `snapshot.debian.org` as Debian's archive stood on 2026-10-27,
  so a rebuild installs the same bytes. A test holds the image's packages to the
  base's plus exactly this one, and its Python packages to the base's exactly.
- **The lookup index** (`/opt/cad-eval/lookup.json`, from `image/lookup_index.py` at
  the build): every public CadQuery name, members through the method resolution order,
  each function once with every class it's on, `cadquery.func` included. Also every
  name in all of OCP's modules, with their pybind11 overloads.
- **The docs index** (`/opt/cad-eval/docs.json`, from `image/docs_index.py`):
  CadQuery's own `doc/*.rst` and `examples/*.py` at the `v2.8.0` tag, fetched by its
  commit, `fb4c6d41863aee270c46ab64397f0d2675e74be0`.
  - **Licence:** Apache-2.0. The builder checks `LICENSE` and refuses a source without
    it, and the index records the repository, tag, commit and licence.
  - **Chunks:** each section by its heading path, code fenced.
  - **Code blocks:** each one is run in the image at the build and marked `runs`.
    Blocks that fail are marked, not dropped; most are fragments that continue an
    earlier block. A block calling CQ-editor's `show_object` is flagged, since the
    sandbox has none.
  - **At v2.8.0:** 263 chunks and 230 code blocks, of which 91 run alone and 40
    call `show_object`.

## The base arm's tools (mqucifer/model-performance#40, A1)

`--arm base` is v2's base: the full toolset. v1's arms and the 30 parts keep their
tools word for word.

**`edit`** is crew's `replace_text`, behaviour and all:
- **What it quotes:** one or more whole lines, exactly once. One leading and one
  trailing newline are forgiven.
- **A refusal says why, under its own rule id:**
  - `edit.twice`: the lines occur more than once, at the line numbers given;
  - `edit.part_of_a_line`: `old` is only part of a line;
  - `edit.closest`: the lines aren't there; the closest block is shown, numbered;
  - `edit.already`: the change may be made already;
  - `edit.not_found`, `edit.same`, `edit.empty`, `edit.no_file`.
- **The parse guard:** an edit that would stop a Python file parsing isn't applied
  (`edit.parse_guard`); the lines are shown as they would have been and as they are.
  A file that already doesn't parse can still be edited, and the reply says so.
- **The reply:** the edited lines, numbered.

**`run` on `write` and `edit`:** `true` runs the file just written; a path runs that
script, for a file it imports, such as `params.py`. One call then changes and runs.
- **What's refused:** a refused edit runs nothing, and a `run` that's neither true nor
  an existing script is refused before anything is written (`not_a_run`, `no_file`).
- **The first compiling part:** a write's or edit's run sets it as `run` does, so
  `calls_to_first_compile` counts it.
- **Several calls in one turn:** carried out in order. An edit's run follows that
  edit, before the turn's next call.

**A failed run's AttributeError** adds where the name is (`hint.py`, from the image's
lookup index):
- **A real name on another class**, v1's commonest error: "`isValid` isn't on
  Workplane. It's on: cq.Shape, cq.Compound, cq.Solid…".
- **A name no class has:** the nearest names, first the class's own, then all of
  CadQuery's: "No CadQuery class has `makeFace`. Names near it: `makeFromWires`…".
- **Where it comes from:** what's installed, not a list anyone wrote.

**`measure`** (from #28, now in the base): a query about the model's own STEP file,
run in the container. The queries are `hole x,y,z`, `distance A B`, `clearance FILE`
and `position A`. The request carries only the path and the query: none of the case's
probes, bounds, volumes or mates. So the model checks against what the spec states,
never against the evaluation's checks.

**`view`** (from #29): the model's own STEP files, rendered by VTK in the v2 image.
- **Views:** `top`, `front`, `side`, `iso`, `exploded`, or `section x=40`.
- **Keep-outs:** only what the model declares. `keepouts` names more of its own STEP
  files (a board, a mating part it modelled from the spec), drawn translucent red.
  Nothing of the case's is drawn: the v1 arm drew the case's hidden mates, which an
  unseen part wouldn't have.
- **Only the latest picture stays.** Earlier ones are replaced by a note through a
  rewrite the records keep, so every request still rebuilds. Each picture is kept in
  `views/<n>.png`.
- **The row** records `views` and `image_tokens`.

**`plan`** (from #30, made generic): before any `write`, `edit` or `run`, the model
sends its parts and files, interfaces, sizes and fits.
- **Each size says where it comes from:**
  - `spec`, quoting the spec's words: the quote must be in the spec's text (markup,
    layout and case aside), and the value one of the quote's numbers;
  - `reference`, quoting a table the session can read;
  - `derived` or `chosen`: recorded, never judged.
- **No answer key:** there's no per-case key of values, so it works on any spec. v1's
  `STATED` judged unseen parts not at all, and once told the model a spool was 70 mm
  wide where the spec says 65. A miss quotes back the model's own entry, never a
  value the evaluation holds.
- **The gate:** `write`, `edit` and `run` open when a plan holds, or after 3 that
  don't.
- **The records:** each check goes to the events, each miss with its entry. The row
  records `plans`, `plan_passed` and `plan_misses`.

## API grounding that transfers (mqucifer/model-performance#40, A2)

The base arm finds CadQuery's names in what's installed, never in a list anyone wrote.
There are no curated call lists anywhere.
- **`lookup`** searches the image's index (`search.py` over `lookup.json`).
  - **Matching:** a member matches by any class it's on, so `Solid.fuse` finds
    `cq.Shape.fuse` (defined there, on Solid too). Each function appears once with every
    class it's on, exact names first, 15 to a `page`.
  - **No match:** the nearest names. v1 returned nothing for 28% of its lookups, some
    of them real inherited names.
  - **OCP:** every name in every module. A class named exactly also lists its
    members, read live.
  - **v1's arms** keep v1's `lookup.py`.
- **`docs`** searches CadQuery's own 2.8.0 documentation and examples by words, three
  sections to a page, with their code. A section whose code calls `show_object`, or
  didn't run on its own at the image's build, says so.
- **The orientation** is the base arm's system prompt (`SYSTEM_BASE`):
  - the version (CadQuery 2.8.0, OCP 7.9.3) and what's installed, exactly;
  - the two layers of the API (the Workplane chain and the shapes it holds), and to
    check a name before using it;
  - each tool named once for what it's for. v1's prompt named three different ways to
    check a fit.
- **Coverage, tested in the image:** every CadQuery name the reference solutions call
  resolves in the index. The references are a corpus to check `lookup` against, never
  shown to the model.
