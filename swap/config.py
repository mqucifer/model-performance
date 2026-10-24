"""The swap's settings, from `config.toml`, checked before anything runs."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG = Path(__file__).with_name("config.toml")
RESTORE_MODES = ("start-dflash", "container", "compose")

# The variables infra's recorded launch must take, so a candidate differs from
# the 27B only in its model (mqucifer/infra#40).
LAUNCH_VARIABLES = ("MODEL_PATH", "SERVED_MODEL_NAME", "SPECULATIVE_ARGS", "CONTAINER_NAME")


class ConfigError(Exception):
    """A setting that would make the swap unsafe, or can't be used."""


@dataclass(frozen=True)
class Config:
    addr_key: str
    user_key: str
    infra_dir: Path
    compose: Path
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

    @property
    def compose_path(self) -> Path:
        return self.infra_dir / self.compose


def load(path: Path = DEFAULT_CONFIG, infra_dir: Path | None = None) -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    spark, infra, serving, litellm = raw["spark"], raw["infra"], raw["serving"], raw["litellm"]
    config = Config(
        addr_key=spark["addr_key"],
        user_key=spark["user_key"],
        infra_dir=(infra_dir or Path(infra["dir"])).expanduser(),
        compose=Path(infra["compose"]),
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
            "every check goes through the proxy, never to SGLang"
        )
    if config.restore not in RESTORE_MODES:
        raise ConfigError(f"serving.restore must be one of {RESTORE_MODES}, not {config.restore!r}")
    if config.candidate_container == config.baseline_container:
        raise ConfigError("the candidate's container must not take the 27B's name")
    if config.candidate_alias == config.baseline_alias:
        raise ConfigError("the candidate's alias must differ from the 27B's")
    if config.poll_s <= 0 or config.ready_timeout_s < config.poll_s:
        raise ConfigError("litellm.poll_s must be positive and below ready_timeout_s")
