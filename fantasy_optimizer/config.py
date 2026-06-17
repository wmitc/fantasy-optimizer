"""Load configuration from ``config.toml`` and/or environment variables.

Precedence (highest first): environment variable -> config.toml -> built-in default.
A ``.env`` file in the working directory is loaded automatically so env vars can live
there during development.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """Resolved configuration for a single league."""

    league_id: int
    year: int
    espn_s2: str | None
    swid: str | None
    team_id: int | None
    team_name: str | None
    proj_weight: float
    pool_size: int
    min_value: float
    lock_value: float
    games_weight: float
    cache_ttl: int

    @property
    def is_private(self) -> bool:
        return bool(self.espn_s2 and self.swid)


# (section, key, env var, caster, default)
_FIELDS: list[tuple[str, str, str, type | object, object]] = [
    ("league", "league_id", "FO_LEAGUE_ID", int, None),
    ("league", "year", "FO_YEAR", int, None),
    ("league", "espn_s2", "FO_ESPN_S2", str, None),
    ("league", "swid", "FO_SWID", str, None),
    ("league", "team_id", "FO_TEAM_ID", int, None),
    ("league", "team_name", "FO_TEAM_NAME", str, None),
    ("valuation", "proj_weight", "FO_PROJ_WEIGHT", float, 0.5),
    ("valuation", "pool_size", "FO_POOL_SIZE", int, 200),
    ("streaming", "min_value", "FO_MIN_VALUE", float, 0.0),
    ("streaming", "lock_value", "FO_LOCK_VALUE", float, 6.0),
    ("streaming", "games_weight", "FO_GAMES_WEIGHT", float, 0.0),
    ("cache", "ttl_seconds", "FO_CACHE_TTL", int, 1800),
]


def _find_config_file(explicit: str | os.PathLike[str] | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        return path
    for candidate in (Path.cwd() / "config.toml", Path(__file__).resolve().parent.parent / "config.toml"):
        if candidate.exists():
            return candidate
    return None


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Build a :class:`Config`, merging env vars over the TOML file over defaults."""
    load_dotenv()

    config_path = _find_config_file(path)
    file_data: dict = {}
    if config_path is not None:
        with config_path.open("rb") as fh:
            file_data = tomllib.load(fh)

    resolved: dict[str, object] = {}
    for section, key, env_var, caster, default in _FIELDS:
        env_val = os.environ.get(env_var)
        if env_val not in (None, ""):
            raw: object = env_val
        else:
            raw = file_data.get(section, {}).get(key, default)
        # treat empty strings (e.g. blank cookies in the example) as "unset"
        if raw == "":
            raw = default
        attr = "cache_ttl" if key == "ttl_seconds" else key
        resolved[attr] = caster(raw) if raw is not None else None

    if resolved.get("league_id") is None:
        raise ValueError(
            "league_id is required. Set it in config.toml ([league] league_id) "
            "or via the FO_LEAGUE_ID environment variable."
        )
    if resolved.get("year") is None:
        raise ValueError("year is required (config.toml [league] year or FO_YEAR).")

    return Config(**resolved)  # type: ignore[arg-type]
