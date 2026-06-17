"""Tests for orchestration helpers and an offline end-to-end build + render."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.console import Console

from fantasy_optimizer import recommend as rec_mod
from fantasy_optimizer.cli import _render, build_parser
from fantasy_optimizer.config import Config
from fantasy_optimizer.recommend import build_recommendation, dedupe_players, resolve_team

YEAR = 2026


class FakePlayer:
    def __init__(self, name, slots, days, avg, status="ACTIVE", team="BOS"):
        self.name = name
        self.playerId = name
        self.eligibleSlots = slots
        self.proTeam = team
        self.injuryStatus = status
        self.schedule = {
            str(d): {"team": "OPP", "date": datetime(2026, 1, 1)} for d in days
        }
        self.stats = {f"{YEAR}_total": {"avg": avg}}


def _avg(pts, reb=4, ast=3, fgm=6, fga=12, ftm=3, fta=4):
    return {"PTS": pts, "REB": reb, "AST": ast, "STL": 1, "BLK": 1, "3PM": 2,
            "FGM": fgm, "FGA": fga, "FTM": ftm, "FTA": fta}


class FakeTeam:
    def __init__(self, team_id, name, abbrev, roster):
        self.team_id = team_id
        self.team_name = name
        self.team_abbrev = abbrev
        self.roster = roster
        self.owners = [{"id": "{ABC}"}]


class FakeClient:
    def __init__(self, config, use_cache=True):
        self.config = config
        self._team = FakeTeam(
            1, "My Team", "MINE",
            [
                FakePlayer("star", ["PG", "G", "UT"], [10, 12], _avg(28)),
                FakePlayer("idle", ["C", "UT"], [10], _avg(12)),
                FakePlayer("hurt", ["SF", "UT"], [10, 11, 12], _avg(20), status="OUT"),
            ],
        )
        self._fas = [
            FakePlayer("fa_good", ["C", "UT"], [11, 12], _avg(22)),
            FakePlayer("fa_meh", ["SG", "UT"], [12], _avg(6)),
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
        return {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 2, "UT": 4, "BE": 4, "IR": 1}

    @property
    def current_matchup_period(self):
        return 3

    @property
    def scoring_period(self):
        return 10

    def matchup_scoring_periods(self, mp=None):
        return [10, 11, 12]


def _config(**over):
    base = dict(
        league_id=1, year=YEAR, espn_s2=None, swid=None, team_id=None, team_name=None,
        proj_weight=0.5, pool_size=200, min_value=0.0, lock_value=6.0,
        games_weight=0.0, cache_ttl=1800,
    )
    base.update(over)
    return Config(**base)


def test_dedupe_players_keeps_first():
    a = FakePlayer("x", ["UT"], [1], _avg(10))
    a2 = FakePlayer("x", ["UT"], [1], _avg(99))
    b = FakePlayer("y", ["UT"], [1], _avg(10))
    out = dedupe_players([a, a2, b])
    assert [p.name for p in out] == ["x", "y"]


def test_resolve_team_falls_back_to_swid(monkeypatch):
    client = FakeClient(_config())
    assert resolve_team(client, _config()).team_name == "My Team"


def test_resolve_team_raises_when_unknown():
    client = FakeClient(_config())
    client.find_my_team = lambda: None  # type: ignore[method-assign]
    with pytest.raises(LookupError):
        resolve_team(client, _config())


def test_build_recommendation_end_to_end(monkeypatch):
    monkeypatch.setattr(rec_mod, "EspnClient", FakeClient)
    rec = build_recommendation(_config(), use_cache=False)

    # Optimizer only fields the 10 starting seats (bench/IR excluded).
    from fantasy_optimizer.optimizer import expand_starting_seats

    assert len(expand_starting_seats(rec.slot_counts)) == 10
    # Only days 10,11,12 remain; injured "hurt" never appears in the lineup.
    assert rec.remaining_days == [10, 11, 12]
    started = {p.name for day in rec.plan.by_day.values() for p, _ in day}
    assert "hurt" not in started
    assert rec.plan.games > 0
    # fa_good fills center games on days 11/12 that the roster otherwise misses.
    assert any(m.add.name == "fa_good" for m in rec.moves)


def test_render_smoke(monkeypatch):
    monkeypatch.setattr(rec_mod, "EspnClient", FakeClient)
    rec = build_recommendation(_config(), use_cache=False)
    console = Console(record=True, width=120)
    _render(rec, console, top=5, explain=True)
    out = console.export_text()
    assert "My Team" in out
    assert "free agents" in out.lower()


def test_parser_builds():
    parser = build_parser()
    args = parser.parse_args(["recommend", "--days", "3", "--explain"])
    assert args.days == 3 and args.explain is True
