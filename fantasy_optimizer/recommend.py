"""Orchestration: pull data, value the pool, optimize the week, suggest streams.

Ties together the client, valuation, schedule, and optimizer modules into a single
:class:`Recommendation` that the CLI renders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from . import schedule
from .client import EspnClient
from .config import Config
from .optimizer import (
    DEFAULT_STARTING_SLOTS,
    StreamMove,
    WeeklyPlan,
    injured_players,
    recommend_streams,
    weekly_plan,
)
from .valuation import value_players


@dataclass
class Recommendation:
    team: Any
    matchup_period: int
    week_days: list[int]
    remaining_days: list[int]
    slot_counts: dict[str, int]
    values: dict
    values_df: pd.DataFrame
    plan: WeeklyPlan
    moves: list[StreamMove]
    roster: list
    free_agents: list
    injured: list


def dedupe_players(players: list) -> list:
    """Drop duplicate players by id, keeping first occurrence."""
    seen: set = set()
    out: list = []
    for p in players:
        pid = getattr(p, "playerId", None)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(p)
    return out


def resolve_team(client: EspnClient, config: Config) -> Any:
    """Find the user's team from config (id/name) or SWID, else raise with the team list."""
    if config.team_id:
        return client.get_team(team_id=config.team_id)
    if config.team_name:
        return client.get_team(name=config.team_name)
    team = client.find_my_team()
    if team is not None:
        return team
    listing = "\n".join(f"  team_id={t.team_id}  {t.team_name} ({t.team_abbrev})" for t in client.teams())
    raise LookupError(
        "Could not determine your team. Set team_id or team_name in config.toml.\n"
        f"Teams in this league:\n{listing}"
    )


def build_recommendation(
    config: Config,
    *,
    use_cache: bool = True,
    matchup_period: int | None = None,
    day_horizon: int | None = None,
    proj_weight: float | None = None,
    min_value: float | None = None,
    as_of: int | None = None,
) -> Recommendation:
    """Fetch, value, optimize, and assemble a full recommendation for the week.

    ``as_of`` is the scoring-period (day) the plan is computed "as of"; days before it are
    treated as already played. It defaults to the live current day, but when ``matchup_period``
    is given explicitly it defaults to that week's first day so past/completed weeks replay
    in full (useful in the off-season).
    """
    client = EspnClient(config, use_cache=use_cache)
    team = resolve_team(client, config)
    roster = list(team.roster)
    free_agents = client.free_agents()

    slot_counts = client.roster_slots() or dict(DEFAULT_STARTING_SLOTS)

    mp = matchup_period or client.current_matchup_period
    week_days = client.matchup_scoring_periods(mp)
    if as_of is None:
        as_of = week_days[0] if matchup_period is not None and week_days else client.scoring_period
    remaining = schedule.remaining_days(week_days, as_of)
    if day_horizon is not None:
        remaining = remaining[:day_horizon]

    pw = config.proj_weight if proj_weight is None else proj_weight
    pool = dedupe_players(roster + free_agents)
    values_df = value_players(pool, pw, config.year)
    values = dict(zip(values_df["player_id"], values_df["value"]))

    plan = weekly_plan(roster, remaining, slot_counts, values, config.games_weight)
    moves = recommend_streams(
        roster,
        free_agents,
        remaining,
        slot_counts,
        values,
        min_value=config.min_value if min_value is None else min_value,
        lock_value=config.lock_value,
        games_weight=config.games_weight,
    )

    return Recommendation(
        team=team,
        matchup_period=mp,
        week_days=week_days,
        remaining_days=remaining,
        slot_counts=slot_counts,
        values=values,
        values_df=values_df,
        plan=plan,
        moves=moves,
        roster=roster,
        free_agents=free_agents,
        injured=injured_players(roster),
    )
