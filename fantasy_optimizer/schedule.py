"""Map the scoring week into days and count each player's games per day.

The scoring "week" is an ESPN *matchup period*, made of several daily *scoring periods*.
``League.matchup_ids`` gives the day IDs for a matchup period; each ``Player.schedule`` is
keyed by those same day IDs (as strings) with the opponent and tip-off datetime. This
module turns that into the games-per-day grids the optimizer consumes.
"""

from __future__ import annotations

import pandas as pd


def normalize_schedule_days(schedule: dict) -> set[int]:
    """Day (scoring-period) IDs a player has a game on, coerced to ``int``.

    ``Player.schedule`` keys arrive as JSON strings; matchup day IDs are ints.
    """
    days: set[int] = set()
    for key in schedule or {}:
        try:
            days.add(int(key))
        except (TypeError, ValueError):
            continue
    return days


def remaining_days(week_days: list[int], current_day: int | None) -> list[int]:
    """Days in the week on or after ``current_day`` (all of them if ``current_day`` is None)."""
    if current_day is None:
        return list(week_days)
    return [d for d in week_days if d >= current_day]


def player_game_days(player, days: list[int]) -> list[int]:
    """Subset of ``days`` on which ``player``'s pro team plays."""
    sched = normalize_schedule_days(getattr(player, "schedule", {}))
    return [d for d in days if d in sched]


def player_opponent(player, day: int) -> str | None:
    """Opponent abbreviation for ``player`` on ``day``, or None if no game."""
    entry = getattr(player, "schedule", {}).get(str(day))
    return entry.get("team") if entry else None


def players_by_day(players, days: list[int]) -> dict[int, list]:
    """For each day, the list of players whose pro team plays that day."""
    by_day: dict[int, list] = {d: [] for d in days}
    for player in players:
        sched = normalize_schedule_days(getattr(player, "schedule", {}))
        for d in days:
            if d in sched:
                by_day[d].append(player)
    return by_day


def games_grid(players, days: list[int]) -> pd.DataFrame:
    """Boolean games-per-day grid indexed by player id.

    Columns: ``name``, one column per day (bool), and ``games`` (count over ``days``).
    """
    rows = []
    for player in players:
        sched = normalize_schedule_days(getattr(player, "schedule", {}))
        row = {"player_id": getattr(player, "playerId", None), "name": getattr(player, "name", None)}
        plays = [d in sched for d in days]
        row.update({d: p for d, p in zip(days, plays)})
        row["games"] = sum(plays)
        rows.append(row)
    cols = ["player_id", "name", *days, "games"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)[cols].set_index("player_id")
