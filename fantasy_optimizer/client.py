"""Thin wrapper around :mod:`espn_api.basketball` with an on-disk TTL cache.

The free-agent pull is the slow ESPN call, so its result is pickled to ``.cache/`` and
reused until it expires. Everything else is a light accessor over the live ``League``.
"""

from __future__ import annotations

import hashlib
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from espn_api.basketball import League
from espn_api.basketball.constant import POSITION_MAP, PRO_TEAM_MAP
from espn_api.basketball.player import Player
from espn_api.basketball.team import Team

from .config import Config

T = TypeVar("T")

_CACHE_DIR = Path(".cache")
# Reverse map of pro-team abbreviation -> id (PRO_TEAM_MAP is id -> abbrev).
_TEAM_ABBR_TO_ID = {abbr: tid for tid, abbr in PRO_TEAM_MAP.items() if isinstance(tid, int)}


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

    def _attach_schedule(self, player: Player) -> None:
        """Populate ``player.schedule`` from the league's pro schedule.

        ``League.free_agents`` builds Player objects without a schedule, so the optimizer
        would see no games for any free agent. We rebuild it the same way Player.__init__
        does, mapping the player's pro team to its games-by-scoring-period.
        """
        if getattr(player, "schedule", None):
            return
        player.schedule = {}
        team_id = _TEAM_ABBR_TO_ID.get(getattr(player, "proTeam", None))
        if team_id is None:
            return
        games_by_period = self.league.pro_schedule.get(team_id, {})
        for period, games in games_by_period.items():
            if not games:
                continue
            game = games[0]
            opp = game["awayProTeamId"] if game["awayProTeamId"] != team_id else game["homeProTeamId"]
            player.schedule[period] = {
                "team": PRO_TEAM_MAP.get(opp),
                "date": datetime.fromtimestamp(game["date"] / 1000.0),
            }

    def free_agents(self, size: int | None = None, position: str | None = None) -> list[Player]:
        """Free-agent / waiver pool for the current week (cached), with schedules attached."""
        size = size or self.config.pool_size
        sp = self.scoring_period
        key = f"fa:{self.config.league_id}:{self.config.year}:{sp}:{size}:{position}"

        def fetch() -> list[Player]:
            players = self.league.free_agents(size=size, position=position)
            for player in players:
                self._attach_schedule(player)
            return players

        return self._cached(key, fetch)

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
