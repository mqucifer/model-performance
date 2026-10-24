"""The swap's settings, from `config.toml`, checked before anything runs."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG = Path(__file__).with_name("config.toml")
RESTORE_MODES = ("start-dflash", "container", "compose")

# The variables a recorded launch may take. Every engine's must take the
# required ones, so a candidate differs from the 27B only in its model, and
# takes its own served name and container (mqucifer/infra#40).
LAUNCH_VARIABLES = ("MODEL_PATH", "SERVED_MODEL_NAME", "SPECULATIVE_ARGS", "CONTAINER_NAME")
REQUIRED_VARIABLES = ("MODEL_PATH", "SERVED_MODEL_NAME", "CONTAINER_NAME")


class ConfigError(Exception):
    """A setting that would make the swap unsafe, or can't be used."""


@dataclass(frozen=True)
class Engine:
    name: str
    compose: Path
    variables: tuple[str, ...]
    seed: bool


@dataclass(frozen=True)
class Config:
    addr_key: str
    user_key: str
    infra_dir: Path
    engines: dict[str, Engine]
    baseline_engine: str
    baseline_container: str
    candidate_project: str
    candidate_container: str
    candidate_served_name: str
    restore: str
    start_dflash: str
    base_url: str
    baseline_alias: str
    candidate_alias: str
    key_file: Path
    key_name: str
    ready_timeout_s: float
    poll_s: float

    def engine(self, name: str) -> Engine:
        if name not in self.engines:
            raise ConfigError(f"no engine {name!r}; known: {', '.join(sorted(self.engines))}")
        return self.engines[name]

    @property
    def baseline(self) -> Engine:
        return self.engine(self.baseline_engine)

    def launch_path(self, engine: Engine) -> Path:
        return self.infra_dir / engine.compose


def load(path: Path = DEFAULT_CONFIG, infra_dir: Path | None = None) -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    spark, infra, serving, litellm = raw["spark"], raw["infra"], raw["serving"], raw["litellm"]
    config = Config(
        addr_key=spark["addr_key"],
        user_key=spark["user_key"],
        infra_dir=(infra_dir or Path(infra["dir"])).expanduser(),
        engines={
            name: Engine(
                name=name,
                compose=Path(engine["compose"]),
                variables=tuple(engine["variables"]),
                seed=bool(engine["seed"]),
            )
            for name, engine in raw["engines"].items()
        },
        baseline_engine=serving["baseline_engine"],
        baseline_container=serving["baseline_container"],
        candidate_project=serving["candidate_project"],
        candidate_container=serving["candidate_container"],
        candidate_served_name=serving["candidate_served_name"],
        restore=serving["restore"],
        start_dflash=serving["start_dflash"],
        base_url=litellm["base_url"].rstrip("/"),
        baseline_alias=litellm["baseline_alias"],
        candidate_alias=litellm["candidate_alias"],
        key_file=Path(litellm["key_file"]).expanduser(),
        key_name=litellm["key_name"],
        ready_timeout_s=float(litellm["ready_timeout_s"]),
        poll_s=float(litellm["poll_s"]),
    )
    check(config)
    return config


def check(config: Config) -> None:
    """Refuse settings that would reach around the proxy or clash with the 27B."""
    url = urlparse(config.base_url)
    if url.hostname not in ("localhost", "127.0.0.1") or url.port != 4000:
        raise ConfigError(
            f"litellm.base_url must be the Mac's LiteLLM on :4000, not {config.base_url}: "
            "every check goes through the proxy, never to the Spark's engine"
        )
    if config.restore not in RESTORE_MODES:
        raise ConfigError(f"serving.restore must be one of {RESTORE_MODES}, not {config.restore!r}")
    config.engine(config.baseline_engine)
    for engine in config.engines.values():
        unknown = set(engine.variables) - set(LAUNCH_VARIABLES)
        missing = set(REQUIRED_VARIABLES) - set(engine.variables)
        if unknown or missing:
            raise ConfigError(
                f"engine {engine.name}: variables must take {', '.join(REQUIRED_VARIABLES)}"
                f" and only {', '.join(LAUNCH_VARIABLES)}"
            )
    if config.candidate_container == config.baseline_container:
        raise ConfigError("the candidate's container must not take the 27B's name")
    if config.candidate_alias == config.baseline_alias:
        raise ConfigError("the candidate's alias must differ from the 27B's")
    if config.poll_s <= 0 or config.ready_timeout_s < config.poll_s:
        raise ConfigError("litellm.poll_s must be positive and below ready_timeout_s")
