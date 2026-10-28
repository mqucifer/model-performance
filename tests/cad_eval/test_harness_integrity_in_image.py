"""The race review of #41's attacks on the harness's own commands, replayed in the v2
image: a `run` plants `python` or `timeout` first on the sandbox's PATH, or leaves a
daemon that kills the harness's processes. The harness runs its commands by absolute
binaries under `env -i`, judges in fresh containers, and ends a run whose reap can't
finish as its own fault. Skipped where the image isn't built."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

import pytest

from cad_eval import container
from cad_eval.tools import PartTools, Tampered

pytestmark = pytest.mark.skipif(
    container.image_id(container.IMAGE_V2) is None, reason=f"{container.IMAGE_V2} isn't built"
)

DAEMON = """
import os, time
if os.fork(): raise SystemExit(0)
os.setsid()
if os.fork(): os._exit(0)
end = time.time() + 120
while time.time() < end:
    open("/work/alive", "w").write(str(time.time())); time.sleep(0.2)
"""
# The reviewer's: a `python` that fakes the reap and forges the measure.
PLANT_PYTHON = r'''
import os
d = "/work/.crew-home/.local/bin"; os.makedirs(d, exist_ok=True)
w = d + "/python"
open(w, "w").write("""#!/bin/sh
if [ "$1" = "-I" ] && [ "$2" = "-" ]; then
  src=$(cat)
  case "$src" in
    *CAD_EVAL_REAPED*) echo "CAD_EVAL_REAPED 0 0"; exit 0;;
    *CAD_EVAL_MEASURE*) echo 'CAD_EVAL_MEASURE {"forged": true}'; exit 0;;
  esac
  printf '%s' "$src" | exec /usr/local/bin/python -I -
fi
exec /usr/local/bin/python "$@"
""")
os.chmod(w, 0o755)
'''
# And a `timeout` that answers for whatever it was asked to run.
PLANT_TIMEOUT = r'''
import os
d = "/work/.crew-home/.local/bin"; os.makedirs(d, exist_ok=True)
w = d + "/timeout"
open(w, "w").write("""#!/bin/sh
echo "CAD_EVAL_REAPED 0 0"
echo 'CAD_EVAL_MEASURE {"forged": true}'
""")
os.chmod(w, 0o755)
'''
# A daemon that kills every process with python in its command line.
KILLER = """
import os, signal, time
if os.fork(): raise SystemExit(0)
os.setsid()
if os.fork(): os._exit(0)
me = os.getpid(); end = time.time() + 120
while time.time() < end:
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) not in (1, me):
            try: cmd = open(f"/proc/{p}/cmdline", "rb").read()
            except OSError: continue
            if b"python" in cmd:
                try: os.kill(int(p), signal.SIGKILL)
                except OSError: pass
"""
STEP = """
import cadquery as cq
cq.exporters.export(cq.Workplane("XY").box(10, 10, 10), "part.step")
"""


def alive(part: Path) -> bool:
    beat = part / "alive"
    if not beat.exists():
        return False
    first = beat.read_text()
    time.sleep(1.5)
    return beat.read_text() != first


@contextlib.contextmanager
def session(tmp_path_factory: pytest.TempPathFactory, label: str):
    part = tmp_path_factory.mktemp(label)
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(part, f"integrity-{label}-{os.getpid()}", image=container.IMAGE_V2)
        assert held.start().ok
        try:
            tools = PartTools(part, held, arm="base")
            tools.plan_passed = True
            yield tools, part
        finally:
            held.stop()


@pytest.mark.parametrize("plant", [PLANT_PYTHON, PLANT_TIMEOUT], ids=["python", "timeout"])
def test_a_planted_command_fakes_neither_the_reap_nor_the_measure(
    tmp_path_factory: pytest.TempPathFactory, plant: str
) -> None:
    with session(tmp_path_factory, "plant") as (tools, part):
        # The part first: once `timeout` is planted, the model's own runs are the
        # plant's, which fools only the model.
        (part / "make.py").write_text(STEP)
        tools.call("run", '{"path": "make.py"}')
        (part / "x.py").write_text(plant + DAEMON)
        ran = tools.call("run", '{"path": "x.py"}')
        if plant is PLANT_PYTHON:
            assert ran.detail["reaped"] >= 1
        assert not alive(part)
        found = tools.call("measure", json.dumps({"path": "part.step", "query": "distance >Z <Z"}))
        assert "forged" not in found.reply and found.outcome == "ok"


def test_a_daemon_that_kills_the_harness_ends_the_run_as_its_fault(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    with session(tmp_path_factory, "killer") as (tools, part):
        (part / "x.py").write_text(KILLER)
        with pytest.raises(Tampered):
            tools.call("run", '{"path": "x.py"}')
        assert tools.troubles.get("reap_unfinished")


def test_the_judging_runs_in_fresh_containers_a_planted_python_cant_reach(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """`done`'s script plants a forging `python` in the model's container and again in
    the judging's re-run, with a daemon each time: the measure is still the part's."""
    with session(tmp_path_factory, "judge") as (tools, part):
        (part / "make.py").write_text(STEP + PLANT_PYTHON + DAEMON)
        tools.call("run", '{"path": "make.py"}')
        request = {"path": "part.step", "probes": [[0, 0, 0], [0, 0, 20]]}
        final = tools.final_case("make.py", {"part": request}, outputs=["part.step"])
        assert final["code"] == 0
        measured = final["measured"]["part"]
        assert "forged" not in measured, measured
        assert measured.get("valid") is True, measured
        assert measured["inside"] == [True, False]
        assert measured["path"] == "part.step"


def test_the_judgings_files_are_mounted_read_only(tmp_path_factory: pytest.TempPathFactory) -> None:
    judged = tmp_path_factory.mktemp("judged")
    (judged / "part.step").write_text("step")
    empty = tmp_path_factory.mktemp("empty")
    with contextlib.chdir(tmp_path_factory.mktemp("work")):
        held = container.held(
            empty,
            f"readonly-{os.getpid()}",
            image=container.IMAGE_V2,
            readonly={judged: "/work/judge"},
        )
        assert held.start().ok
        try:
            wrote = held.run_fixed(["/bin/sh", "-c", "echo x > judge/part.step"], timeout=30)
            assert wrote.code != 0
            assert (
                held.run_fixed(["/bin/cat", "judge/part.step"], timeout=30).output.strip() == "step"
            )
        finally:
            held.stop()
    assert (judged / "part.step").read_text() == "step"
