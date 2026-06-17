"""Tests for the season backtest engine (offline)."""

from __future__ import annotations

from fantasy_optimizer import simulate as sim_mod
from fantasy_optimizer.config import Config
from fantasy_optimizer.optimizer import WeeklyPlan, weekly_plan
from fantasy_optimizer.simulate import accumulate_categories, greedy_stream, run_backtest

YEAR = 2026


class FakePlayer:
    def __init__(self, name, slots, days, pts):
        self.name = name
        self.playerId = name
        self.eligibleSlots = slots
        self.proTeam = "BOS"
        self.injuryStatus = "ACTIVE"
        self.schedule = {str(d): {"team": "OPP", "date": None} for d in days}
        self.stats = {f"{YEAR}_total": {"avg": {
            "PTS": pts, "REB": 4, "AST": 3, "STL": 1, "BLK": 1, "3PM": 2,
            "FGM": 6, "FGA": 12, "FTM": 3, "FTA": 4,
        }}}


def test_accumulate_categories_sums_started_players():
    p = FakePlayer("p", ["UT"], [1], pts=20)
    plan = WeeklyPlan(by_day={1: [(p, "UT")], 2: [(p, "UT")]}, value=0.0, games=2)
    totals = {c: 0.0 for c in sim_mod.COUNTING_CATS}
    accumulate_categories(plan, YEAR, totals)
    assert totals["PTS"] == 40  # 20 over two started games
    assert totals["REB"] == 8


def test_greedy_stream_fills_gap_and_adds_games():
    slots = {"UT": 1}
    days = [1, 2, 3]
    rostered = FakePlayer("low", ["UT"], [1], pts=8)
    fa = FakePlayer("fa", ["UT"], [2, 3], pts=24)
    values = {"low": 0.5, "fa": 5.0}
    base = weekly_plan([rostered], days, slots, values)
    streamed, adds = greedy_stream(
        [rostered], [fa], days, slots, values,
        max_adds=1, min_value=0.0, lock_value=6.0, games_weight=0.0,
    )
    assert [a.name for a in adds] == ["fa"]
    assert streamed.games > base.games


def test_greedy_stream_respects_budget():
    slots = {"UT": 2}
    days = [1]
    rostered = [FakePlayer("r1", ["UT"], [], pts=1), FakePlayer("r2", ["UT"], [], pts=1)]
    fas = [FakePlayer(f"fa{i}", ["UT"], [1], pts=20) for i in range(5)]
    values = {"r1": 0.1, "r2": 0.1, **{f"fa{i}": 3.0 for i in range(5)}}
    _, adds = greedy_stream(
        rostered, fas, days, slots, values,
        max_adds=2, min_value=0.0, lock_value=6.0, games_weight=0.0,
    )
    assert len(adds) == 2  # capped at the budget


# --- offline end-to-end run_backtest ----------------------------------------


class FakeLeague:
    matchup_ids = {1: ["1", "2", "3"], 2: ["4", "5", "6"]}


class FakeTeam:
    def __init__(self, roster):
        self.team_id = 14
        self.team_name = "Monstars"
        self.team_abbrev = "MON"
        self.roster = roster
        self.owners = []


class FakeClient:
    def __init__(self, config, use_cache=True):
        self.league = FakeLeague()
        self._team = FakeTeam([
            FakePlayer("star", ["PG", "UT"], [1, 2, 4, 5], pts=28),
            FakePlayer("bench", ["C", "UT"], [1], pts=6),
        ])
        self._fas = [
            FakePlayer("streamer", ["C", "UT"], [3, 6], pts=18),
            FakePlayer("scrub", ["SG", "UT"], [2], pts=3),
        ]

    def find_my_team(self):
        return self._team

    def get_team(self, *, team_id=None, name=None):
        return self._team

    def teams(self):
        return [self._team]

    def free_agents(self, size=None, position=None):
        return self._fas

    def roster_slots(self):
        return {"PG": 1, "C": 1, "UT": 1, "BE": 4, "IR": 1}

    def matchup_scoring_periods(self, mp=None):
        return [int(x) for x in self.league.matchup_ids[mp]]


def _config(**over):
    base = dict(
        league_id=1, year=YEAR, espn_s2=None, swid=None, team_id=14, team_name=None,
        proj_weight=0.5, pool_size=200, min_value=0.0, lock_value=6.0,
        games_weight=0.0, cache_ttl=1800,
    )
    base.update(over)
    return Config(**base)


def test_run_backtest_offline(monkeypatch):
    monkeypatch.setattr(sim_mod, "EspnClient", FakeClient)
    result = run_backtest(_config(), use_cache=False, max_adds=2)
    assert result.team_name == "Monstars"
    assert [w.matchup_period for w in result.weeks] == [1, 2]
    # Streaming never reduces games, and should add at least one game somewhere.
    assert result.total_extra_games >= 1
    assert result.total_stream_games >= result.total_static_games
    # Category deltas are non-negative for points (more started games -> more production).
    assert result.stream_categories["PTS"] >= result.static_categories["PTS"]
