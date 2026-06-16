"""Unit tests for scoring-week -> games-per-day mapping."""

from __future__ import annotations

from fantasy_optimizer.schedule import (
    games_grid,
    normalize_schedule_days,
    player_game_days,
    player_opponent,
    players_by_day,
    remaining_days,
)


class _FakePlayer:
    """Mimics espn-api Player.schedule: keyed by string day id -> {team, date}."""

    def __init__(self, name, game_days, opponents=None):
        self.name = name
        self.playerId = name
        opponents = opponents or {}
        self.schedule = {str(d): {"team": opponents.get(d, "OPP"), "date": None} for d in game_days}


def test_normalize_handles_string_keys():
    assert normalize_schedule_days({"10": {}, "12": {}}) == {10, 12}
    assert normalize_schedule_days({}) == set()
    assert normalize_schedule_days(None) == set()


def test_remaining_days_filters_on_current():
    week = [10, 11, 12, 13, 14, 15, 16]
    assert remaining_days(week, 13) == [13, 14, 15, 16]
    assert remaining_days(week, None) == week


def test_player_game_days_intersects_week():
    p = _FakePlayer("p", game_days=[10, 12, 16, 20])
    assert player_game_days(p, [10, 11, 12, 13, 14, 15, 16]) == [10, 12, 16]


def test_player_opponent_lookup():
    p = _FakePlayer("p", game_days=[10, 12], opponents={10: "LAL", 12: "BOS"})
    assert player_opponent(p, 10) == "LAL"
    assert player_opponent(p, 12) == "BOS"
    assert player_opponent(p, 11) is None


def test_players_by_day_groups_correctly():
    a = _FakePlayer("a", game_days=[10, 12])
    b = _FakePlayer("b", game_days=[10, 11])
    by_day = players_by_day([a, b], [10, 11, 12])
    assert {p.name for p in by_day[10]} == {"a", "b"}
    assert {p.name for p in by_day[11]} == {"b"}
    assert {p.name for p in by_day[12]} == {"a"}


def test_games_grid_counts_and_columns():
    a = _FakePlayer("a", game_days=[10, 12])
    b = _FakePlayer("b", game_days=[10, 11, 12])
    days = [10, 11, 12]
    grid = games_grid([a, b], days)
    assert grid.loc["a", "games"] == 2
    assert grid.loc["b", "games"] == 3
    assert grid.loc["a", 11] is False or grid.loc["a", 11] == False  # noqa: E712
    assert grid.loc["b", 11] == True  # noqa: E712


def test_games_grid_empty():
    grid = games_grid([], [10, 11])
    assert grid.empty
