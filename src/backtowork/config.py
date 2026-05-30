"""Config loading. TOML in, a list of built Providers + settings out.

Search order for the config file:
  1. --config PATH (handled in cli.py)
  2. $BACKTOWORK_CONFIG
  3. ./backtowork.toml
  4. %APPDATA%\\backtowork\\config.toml      (Windows)
  5. ~/.config/backtowork/config.toml
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .providers.base import Provider, build


def _user_config_locations() -> list[Path]:
    locs: list[Path] = [Path("backtowork.toml")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        locs.append(Path(appdata) / "backtowork" / "config.toml")
    locs.append(Path.home() / ".config" / "backtowork" / "config.toml")
    return locs


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get("BACKTOWORK_CONFIG")
    if env:
        return Path(env)
    for loc in _user_config_locations():
        if loc.exists():
            return loc
    return None


def load_providers(path: Path) -> tuple[list[Provider], dict]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    providers: list[Provider] = []
    for entry in raw.get("provider", []):
        kind = entry.get("kind")
        name = entry.get("name", kind)
        if not kind:
            raise ValueError(f"provider entry missing 'kind': {entry}")
        options = {k: v for k, v in entry.items() if k not in ("kind", "name")}
        providers.append(build(kind, name, options))
    settings = raw.get("settings", {})
    return providers, settings
