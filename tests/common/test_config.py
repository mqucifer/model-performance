"""The shared settings refuse a proxy around :4000, and records that could leave the Mac."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.config import DEFAULT_CONFIG, ConfigError, load

GOOD = DEFAULT_CONFIG.read_text(encoding="utf-8")


def settings_with(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(GOOD.replace(old, new), encoding="utf-8")
    return path


def test_the_repository_config_loads(tmp_path: Path) -> None:
    settings = load(home=tmp_path)
    assert settings.base_url == "http://localhost:4000"
    assert settings.records_dir == tmp_path / ".local/share/model-performance/records"
    assert settings.call_cap == 150


@pytest.mark.parametrize(
    "url", ["http://localhost:30000", "http://spark:4000", "https://api.example.com"]
)
def test_a_proxy_that_isnt_the_macs_4000_is_refused(tmp_path: Path, url: str) -> None:
    path = settings_with(tmp_path, "http://localhost:4000", url)
    with pytest.raises(ConfigError, match=":4000"):
        load(path, home=tmp_path)


def test_records_on_documents_are_refused(tmp_path: Path) -> None:
    path = settings_with(
        tmp_path, "~/.local/share/model-performance/records", "~/Documents/records"
    )
    with pytest.raises(ConfigError, match="iCloud"):
        load(path, home=tmp_path)


def test_records_inside_a_checkout_are_refused(tmp_path: Path) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    path = settings_with(tmp_path, "~/.local/share/model-performance/records", "~/repo/var/records")
    with pytest.raises(ConfigError, match="outside any checkout"):
        load(path, home=tmp_path)
