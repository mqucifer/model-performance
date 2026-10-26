"""Proves compose.yaml launches what the Spark's SGLang container runs, flag by flag.

Compares a `docker inspect` of the container with `docker compose config` of
compose.yaml, rendered with no swap variables set, so the 27B's defaults:

- each SGLang flag, by the value SGLang uses (argparse keeps the last of a
  repeated flag), and no flag on one side only;
- the image digest, the entrypoint, and the host settings: network, IPC,
  privileged, security options, shared memory, GPUs and the restart policy;
- the mounts;
- the env, by name only. A value is never compared or printed: the
  container's env holds HF_TOKEN.

    python3 check_launch.py INSPECT.json IMAGE_INSPECT.json [COMPOSE_CONFIG.json]

INSPECT.json is `docker inspect qwen3.8-27b-sglang` and IMAGE_INSPECT.json is
`docker image inspect` of its image, which says which env names are the
image's own. COMPOSE_CONFIG.json is `docker compose -f compose.yaml config
--format json`, run here when it's left out, with HOME set to the Spark's.
Exits 0 when they match, and 1 with each difference when they don't.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHER = ["python3", "-m", "sglang.launch_server"]


def one(inspect: object) -> dict:
    """`docker inspect` prints a list of one."""
    return inspect[0] if isinstance(inspect, list) else inspect


def flags(args: list[str]) -> dict[str, str | None]:
    """Each flag's last value, as argparse sees it; a flag with no value maps to None."""
    if args[: len(LAUNCHER)] != LAUNCHER:
        raise ValueError(f"not an SGLang launch: {args[:3]}")
    rest = args[len(LAUNCHER) :]
    found: dict[str, str | None] = {}
    i = 0
    while i < len(rest):
        flag = rest[i]
        if not flag.startswith("--"):
            raise ValueError(f"a value with no flag: {flag}")
        if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            found[flag] = rest[i + 1]
            i += 2
        else:
            found[flag] = None
            i += 1
    return found


def digest(ref: str) -> str:
    return ref.rpartition("@")[2]



def compare(name: str, running: object, recorded: object) -> list[str]:
    return [] if running == recorded else [f"{name}: the container has {running!r}, compose.yaml {recorded!r}"]


def differences(inspect: dict, image: dict, config: dict) -> list[str]:
    service = config["services"]["sglang"]
    host = inspect["HostConfig"]
    found: list[str] = []

    running, recorded = flags(inspect["Args"]), flags(service["command"])
    for flag in sorted(running.keys() | recorded.keys()):
        if flag not in recorded:
            found.append(f"{flag}: the container has it, compose.yaml doesn't")
        elif flag not in running:
            found.append(f"{flag}: compose.yaml has it, the container doesn't")
        else:
            found += compare(flag, running[flag], recorded[flag])

    found += compare("image digest", digest(inspect["Config"]["Image"]), digest(service["image"]))
    found += compare("entrypoint", [inspect["Path"]], service.get("entrypoint") or image["Config"]["Entrypoint"])
    found += compare("container name", inspect["Name"].lstrip("/"), service["container_name"])
    found += compare("network", host["NetworkMode"], service.get("network_mode"))
    found += compare("ipc", host["IpcMode"], service.get("ipc"))
    found += compare("privileged", host["Privileged"], service.get("privileged", False))
    found += compare("security options", host["SecurityOpt"] or [], service.get("security_opt", []))
    found += compare("shared memory", host["ShmSize"], int(service.get("shm_size", 0)))
    found += compare("restart", host["RestartPolicy"]["Name"], service.get("restart", "no"))
    gpus = [
        {"count": r["Count"], "capabilities": r["Capabilities"]} for r in host.get("DeviceRequests") or []
    ]
    found += compare(
        "gpus",
        gpus,
        [{"count": g["count"], "capabilities": g.get("capabilities", [["gpu"]])} for g in service.get("gpus", [])],
    )
    found += compare(
        "mounts",
        sorted((m["Source"], m["Destination"], m["RW"]) for m in inspect["Mounts"]),
        sorted((v["source"], v["target"], not v.get("read_only", False)) for v in service.get("volumes", [])),
    )

    image_env = {e.split("=", 1)[0] for e in image["Config"]["Env"] or []}
    launch_env = {e.split("=", 1)[0] for e in inspect["Config"]["Env"] or []} - image_env
    found += compare("env names the launch sets", sorted(launch_env), sorted(service.get("environment", {})))
    return found


def rendered(home: str) -> dict:
    """compose.yaml with no swap variables, so the 27B's defaults."""
    env = {
        **os.environ,
        "HOME": home,
        "DOCKER_CONFIG": os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker")),
    }
    for name in ("MODEL_PATH", "SERVED_MODEL_NAME", "SPECULATIVE_ARGS", "CONTAINER_NAME", "WEIGHTS_CACHE"):
        env.pop(name, None)
    out = subprocess.run(
        ["docker", "compose", "-f", str(HERE / "compose.yaml"), "config", "--format", "json"],
        capture_output=True, text=True, env=env, check=True,
    )
    return json.loads(out.stdout)


def home_of(inspect: dict) -> str:
    """The Spark's home directory, from the weights cache's mount."""
    for m in inspect["Mounts"]:
        if m["Destination"] == "/root/.cache/huggingface":
            return m["Source"].split("/Qwen3.8-27B-SGLang-DGX-Spark/")[0]
    raise ValueError("no weights cache among the container's mounts")


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    inspect = one(json.loads(Path(argv[0]).read_text()))
    image = one(json.loads(Path(argv[1]).read_text()))
    config = json.loads(Path(argv[2]).read_text()) if len(argv) == 3 else rendered(home_of(inspect))
    found = differences(inspect, image, config)
    for line in found:
        print(line)
    if not found:
        print(f"launch: compose.yaml matches the container, {len(flags(inspect['Args']))} flags")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
