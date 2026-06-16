"""Thin wrapper around :mod:`espn_api.basketball` with an on-disk TTL cache.

The free-agent pull is the slow ESPN call, so its result is pickled to ``.cache/`` and
reused until it expires. Everything else is a light accessor over the live ``League``.
"""

from __future__ import annotations

import hashlib
import pickle
import time
from pathlib import Path
from typing import Callable, TypeVar

from espn_api.basketball import League
from espn_api.basketball.constant import POSITION_MAP
from espn_api.basketball.player import Player
from espn_api.basketball.team import Team

from .config import Config

T = TypeVar("T")

_CACHE_DIR = Path(".cache")


class EspnClient:
    """Authenticated handle to one ESPN fantasy basketball league."""

    def __init__(self, config: Config, *, use_cache: bool = True):
        self.config = config
        self.use_cache = use_cache
        self._league: League | None = None

    # -- league handle --------------------------------------------------------
    @property
    def league(self) -> League:
        if self._league is None:
            self._league = League(
                league_id=self.config.league_id,
                year=self.config.year,
                espn_s2=self.config.espn_s2 or None,
                swid=self.config.swid or None,
            )
        return self._league

    # -- caching --------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode()).hexdigest()[:16]
        return _CACHE_DIR / f"{digest}.pkl"

    def _cached(self, key: str, fn: Callable[[], T]) -> T:
        """Return ``fn()``, served from a pickled cache file when fresh."""
        if not self.use_cache:
            return fn()
        path = self._cache_path(key)
        if path.exists() and (time.time() - path.stat().st_mtime) < self.config.cache_ttl:
            with path.open("rb") as fh:
                return pickle.load(fh)
        result = fn()
        _CACHE_DIR.mkdir(exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(result, fh)
        return result

    # -- accessors ------------------------------------------------------------
    @property
    def current_matchup_period(self) -> int:
        return self.league.currentMatchupPeriod

    @property
    def scoring_period(self) -> int:
        return self.league.scoringPeriodId

    def matchup_scoring_periods(self, matchup_period: int | None = None) -> list[int]:
        """Scoring-period (day) IDs that make up a matchup period (the scoring week)."""
        mp = matchup_period or self.current_matchup_period
        return [int(sp) for sp in self.league.matchup_ids.get(mp, [])]

    def teams(self) -> list[Team]:
        return self.league.teams

    def get_team(self, *, team_id: int | None = None, name: str | None = None) -> Team:
        """Look up a team by id, name, or abbreviation (case-insensitive)."""
        for team in self.league.teams:
            if team_id is not None and team.team_id == team_id:
                return team
            if name is not None and name.lower() in (
                team.team_name.lower(),
                team.team_abbrev.lower(),
            ):
                return team
        raise LookupError(f"No team matching team_id={team_id!r} name={name!r}")

    def find_my_team(self) -> Team | None:
        """Best-effort match of the authenticated user's team via the SWID owner id."""
        swid = (self.config.swid or "").strip()
        if not swid:
            return None
        swid_norm = swid.strip("{}").lower()
        for team in self.league.teams:
            for owner in getattr(team, "owners", []) or []:
                owner_id = owner.get("id") if isinstance(owner, dict) else owner
                if owner_id and str(owner_id).strip("{}").lower() == swid_norm:
                    return team
        return None

    def free_agents(self, size: int | None = None, position: str | None = None) -> list[Player]:
        """Free-agent / waiver pool for the current week (cached)."""
        size = size or self.config.pool_size
        sp = self.scoring_period
        key = f"fa:{self.config.league_id}:{self.config.year}:{sp}:{size}:{position}"
        return self._cached(key, lambda: self.league.free_agents(size=size, position=position))

    def roster_slots(self) -> dict[str, int]:
        """Starting + bench/IR slot counts, e.g. {'PG': 1, ..., 'UT': 3, 'BE': 4, 'IR': 1}.

        Pulled from the raw ``mSettings`` payload because the library's Settings object
        does not expose ``rosterSettings.lineupSlotCounts``.
        """
        data = self.league.espn_request.league_get(params={"view": "mSettings"})
        counts = data["settings"]["rosterSettings"]["lineupSlotCounts"]
        slots: dict[str, int] = {}
        for slot_id, count in counts.items():
            if count:
                slots[POSITION_MAP.get(int(slot_id), str(slot_id))] = count
        return slots
