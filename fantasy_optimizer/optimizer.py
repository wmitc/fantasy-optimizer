"""Daily lineup assignment and streaming add/drop search.

For each remaining day of the scoring week we solve a max-weight bipartite matching of
available players to starting-lineup seats (``scipy.optimize.linear_sum_assignment``). The
weekly value is the sum over days; because each started game contributes the player's 8-cat
value, the objective naturally *plays more games with better players*.

The streaming search then asks: which free-agent add (and which roster drop) most increases
that weekly value? That is the heart of the tool -- swapping marginal players to squeeze
more productive games out of the week.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from .schedule import players_by_day

# Lineup slots that are not part of the active starting lineup.
NON_STARTING_SLOTS = {"BE", "IR"}

# Fallback starting lineup when live league settings can't be fetched.
# The user's league: 1 PG, 1 SG, 1 SF, 1 PF, 2 C, 4 UTIL (10 active) + 4 bench + 1 IR.
DEFAULT_STARTING_SLOTS = {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 2, "UT": 4}

# Injury statuses that make a player unavailable to accrue stats this week.
UNAVAILABLE_STATUSES = {"OUT", "SUSPENSION", "INJURY_RESERVE", "NINETY_DAY_DL", "DL"}


@dataclass
class WeeklyPlan:
    """Result of optimizing a roster over the week's remaining days."""

    by_day: dict[int, list[tuple[Any, str]]]  # day -> [(player, slot)]
    value: float
    games: int


@dataclass
class StreamMove:
    """A recommended add/drop swap and its effect on weekly value."""

    add: Any
    drop: Any
    gain: float
    new_value: float
    extra: dict = field(default_factory=dict)


def _value_of(values: dict, player) -> float:
    return float(values.get(getattr(player, "playerId", None), 0.0))


def is_available(player) -> bool:
    """True unless the player is hard-out (OUT / IR / suspended) this week."""
    status = getattr(player, "injuryStatus", None)
    return status not in UNAVAILABLE_STATUSES


def expand_starting_seats(slot_counts: dict[str, int]) -> list[str]:
    """Expand ``{'PG': 1, ..., 'UT': 3}`` into a flat list of seat slot names."""
    seats: list[str] = []
    for slot, count in slot_counts.items():
        if slot in NON_STARTING_SLOTS:
            continue
        seats.extend([slot] * int(count))
    return seats


def assign_day(
    players: list,
    seats: list[str],
    values: dict,
    games_weight: float = 0.0,
) -> tuple[list[tuple[Any, str]], float]:
    """Optimally fill ``seats`` from ``players`` to maximize total value for one day.

    A player fills a seat only if the seat's slot is in the player's ``eligibleSlots``.
    ``games_weight`` is added to each started game's value, so a positive value makes the
    optimizer prefer fielding a marginal player over leaving a seat empty.
    """
    if not players or not seats:
        return [], 0.0

    n, m = len(players), len(seats)
    large = 1e6  # forbid ineligible pairings; exceeds any realistic value magnitude

    # Columns: m real seats + n "bench" dummies (one per player) so a player can sit and a
    # seat can stay empty. Minimization: eligible seat costs -(value + games_weight); a
    # player only takes a real seat when that beats their 0-cost bench, i.e. value+gw > 0.
    cost = np.full((n, m + n), large)
    eligible = [set(getattr(p, "eligibleSlots", [])) for p in players]
    for i, p in enumerate(players):
        weight = _value_of(values, p) + games_weight
        for j, slot in enumerate(seats):
            if slot in eligible[i]:
                cost[i, j] = -weight
        cost[i, m + i] = 0.0  # this player's bench seat

    rows, cols = linear_sum_assignment(cost)

    assignments: list[tuple[Any, str]] = []
    total = 0.0
    for i, j in zip(rows, cols):
        if j < m and seats[j] in eligible[i]:
            assignments.append((players[i], seats[j]))
            total += _value_of(values, players[i])
    return assignments, total


def weekly_plan(
    players: list,
    days: list[int],
    slot_counts: dict[str, int],
    values: dict,
    games_weight: float = 0.0,
) -> WeeklyPlan:
    """Optimize the lineup for every day and aggregate value and games played."""
    seats = expand_starting_seats(slot_counts)
    available = [p for p in players if is_available(p)]
    by_day = players_by_day(available, days)

    plan: dict[int, list[tuple[object, str]]] = {}
    total = 0.0
    games = 0
    for day in days:
        assignments, value = assign_day(by_day[day], seats, values, games_weight)
        plan[day] = assignments
        total += value
        games += len(assignments)
    return WeeklyPlan(by_day=plan, value=total, games=games)


def recommend_streams(
    roster: list,
    free_agents: list,
    days: list[int],
    slot_counts: dict[str, int],
    values: dict,
    *,
    min_value: float = 0.0,
    lock_value: float = 6.0,
    max_moves: int = 10,
    games_weight: float = 0.0,
    max_candidates: int = 50,
) -> list[StreamMove]:
    """Rank add/drop swaps by how much they raise the week's optimized value.

    For each free agent (value >= ``min_value``) we find the best droppable roster player
    (value < ``lock_value``) and record the resulting weekly-value gain. Returns the top
    ``max_moves`` distinct adds with a positive gain, best first.
    """
    baseline = weekly_plan(roster, days, slot_counts, values, games_weight).value

    candidates = sorted(
        (fa for fa in free_agents if _value_of(values, fa) >= min_value),
        key=lambda fa: _value_of(values, fa),
        reverse=True,
    )[:max_candidates]
    droppable = [p for p in roster if _value_of(values, p) < lock_value]

    moves: list[StreamMove] = []
    for fa in candidates:
        best: StreamMove | None = None
        for drop in droppable:
            new_roster = [p for p in roster if p is not drop] + [fa]
            new_value = weekly_plan(new_roster, days, slot_counts, values, games_weight).value
            gain = new_value - baseline
            if best is None or gain > best.gain:
                best = StreamMove(add=fa, drop=drop, gain=gain, new_value=new_value)
        if best is not None and best.gain > 1e-9:
            moves.append(best)

    moves.sort(key=lambda m: m.gain, reverse=True)
    return moves[:max_moves]


def injured_players(roster: list) -> list:
    """Roster players who are hard-out -- candidates for the IR slot."""
    return [p for p in roster if not is_available(p)]
