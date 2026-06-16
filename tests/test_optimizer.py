"""Unit tests for the daily assignment and streaming search."""

from __future__ import annotations

from fantasy_optimizer.optimizer import (
    assign_day,
    expand_starting_seats,
    injured_players,
    recommend_streams,
    weekly_plan,
)


class P:
    def __init__(self, name, slots, days, status="ACTIVE"):
        self.name = name
        self.playerId = name
        self.eligibleSlots = slots
        self.schedule = {str(d): {"team": "X", "date": None} for d in days}
        self.injuryStatus = status


def vals(**kw):
    return dict(kw)


def test_expand_seats_excludes_bench_and_ir():
    seats = expand_starting_seats({"PG": 1, "SG": 1, "UT": 3, "BE": 4, "IR": 1})
    assert sorted(seats) == ["PG", "SG", "UT", "UT", "UT"]


def test_assign_day_respects_eligibility_and_picks_best():
    a = P("a", ["PG", "G", "UT"], [1])
    b = P("b", ["SG", "G", "UT"], [1])
    seats = ["PG", "UT"]
    assigns, total = assign_day([a, b], seats, vals(a=5, b=3))
    placed = {p.name: slot for p, slot in assigns}
    assert placed["a"] == "PG"  # only a can play PG
    assert placed["b"] == "UT"
    assert total == 8


def test_assign_day_leaves_seat_empty_when_no_eligible():
    a = P("a", ["PG", "UT"], [1])
    assigns, total = assign_day([a], ["C"], vals(a=5))
    assert assigns == []
    assert total == 0.0


def test_assign_day_benches_negative_value_by_default():
    a = P("a", ["UT"], [1])
    assigns, total = assign_day([a], ["UT"], vals(a=-2))
    assert assigns == []  # negative value -> better to leave empty
    assert total == 0.0


def test_games_weight_starts_marginal_player():
    a = P("a", ["UT"], [1])
    assigns, total = assign_day([a], ["UT"], vals(a=-1), games_weight=3.0)
    assert [p.name for p, _ in assigns] == ["a"]  # +3 bonus makes fielding worthwhile
    assert total == -1.0


def test_weekly_plan_aggregates_and_excludes_injured():
    slots = {"UT": 1}
    days = [1, 2]
    healthy = P("h", ["UT"], [1, 2])
    out = P("o", ["UT"], [1, 2], status="OUT")
    plan = weekly_plan([healthy, out], days, slots, vals(h=4, o=10))
    # Out player is excluded even though higher value and scheduled both days.
    assert plan.games == 2
    assert plan.value == 8
    assert all(p.name == "h" for day in plan.by_day.values() for p, _ in day)


def test_injured_players_helper():
    healthy = P("h", ["UT"], [1])
    out = P("o", ["UT"], [1], status="OUT")
    assert [p.name for p in injured_players([healthy, out])] == ["o"]


def test_recommend_streams_prefers_high_value_fa_on_open_day():
    slots = {"UT": 1}
    days = [1, 2]
    # Roster: one player who only plays day 1, leaving day 2's seat empty.
    rostered = P("low", ["UT"], [1])
    # FA who plays day 2 (fills the gap) and is more valuable.
    fa_good = P("good", ["UT"], [1, 2])
    fa_weak = P("weak", ["UT"], [2])
    values = vals(low=1.0, good=5.0, weak=0.2)
    moves = recommend_streams(
        [rostered], [fa_good, fa_weak], days, slots, values,
        min_value=0.0, lock_value=6.0,
    )
    assert moves, "expected at least one positive-gain move"
    assert moves[0].add.name == "good"
    assert moves[0].drop.name == "low"
    assert moves[0].gain > 0


def test_recommend_streams_respects_locked_players():
    slots = {"UT": 1}
    days = [1]
    star = P("star", ["UT"], [1])
    fa = P("fa", ["UT"], [1])
    values = vals(star=9.0, fa=8.0)  # star above lock_value -> never dropped
    moves = recommend_streams([star], [fa], days, slots, values, lock_value=6.0)
    assert moves == []
