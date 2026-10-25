"""The shared settings, from the repository's `config.toml`, checked before anything runs."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG = Path(__file__).parents[1] / "config.toml"


class ConfigError(Exception):
    """A setting that would send a call around the proxy, or a record somewhere it mustn't go."""


@dataclass(frozen=True)
class Settings:
    records_dir: Path
    work_dir: Path
    base_url: str
    key_file: Path
    key_name: str
    call_cap: int
    crew_events: Path
    crew_coverage: Path


def load(path: Path = DEFAULT_CONFIG, home: Path | None = None) -> Settings:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    records, work, litellm, crew = raw["records"], raw["work"], raw["litellm"], raw["crew"]
    settings = Settings(
        records_dir=_path(records["dir"], home),
        work_dir=_path(work["dir"], home),
        base_url=litellm["base_url"].rstrip("/"),
        key_file=_path(litellm["key_file"], home),
        key_name=litellm["key_name"],
        call_cap=int(litellm["call_cap"]),
        crew_events=_path(crew["events"], home),
        crew_coverage=_path(crew["coverage"], home),
    )
    check(settings, home or Path.home())
    return settings


def check(settings: Settings, home: Path) -> None:
    """Refuse a proxy that isn't the Mac's :4000, and directories a record could leave it from."""
    url = urlparse(settings.base_url)
    if url.hostname not in ("localhost", "127.0.0.1") or url.port != 4000:
        raise ConfigError(
            f"litellm.base_url must be the Mac's LiteLLM on :4000, not {settings.base_url}: "
            "every model call goes through the proxy"
        )
    for name, path in (("records.dir", settings.records_dir), ("work.dir", settings.work_dir)):
        if not path.is_absolute():
            raise ConfigError(f"{name} must be absolute, not {path}")
        if path.is_relative_to(home / "Documents"):
            raise ConfigError(f"{name} must be off ~/Documents, which iCloud can sync")
        checkout = inside_checkout(path)
        if checkout is not None:
            raise ConfigError(f"{name} must be outside any checkout, not inside {checkout}")
    if settings.call_cap < 1:
        raise ConfigError("litellm.call_cap must be at least 1")


def inside_checkout(path: Path) -> Path | None:
    """The git checkout `path` would land in, if any, looking up from where it exists."""
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _path(value: str, home: Path | None) -> Path:
    if home is not None and value.startswith("~/"):
        return home / value[2:]
    return Path(value).expanduser()
