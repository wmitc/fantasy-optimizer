"""Season backtest: set-and-forget vs. streaming over a completed season.

For each scoring week we compare two strategies on the same roster:

* **static** -- the roster as-is, optimally arranged each day (no waiver moves);
* **stream** -- greedily apply the best add/drop swaps (up to a weekly budget) to fill open
  lineup days with available free agents.

Each started game is credited the player's season-average stat line, so the comparison
isolates the effect of *fielding more productive games* -- the core streaming thesis.

Fidelity caveats (the data ESPN exposes for a finished season):
* rosters, free-agent pool, and injury statuses are the season's **final** state, not the
  state during each historical week;
* production is modeled as **season-average per scheduled game**, not the literal box score.

So this measures the *opportunity* streaming creates given real schedules, not a
move-by-move replay of what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .client import EspnClient
from .config import Config
from .optimizer import DEFAULT_STARTING_SLOTS, WeeklyPlan, recommend_streams, weekly_plan
from .recommend import dedupe_players, resolve_team
from .valuation import COUNTING_CATS, value_players


@dataclass
class WeekResult:
    matchup_period: int
    days: int
    static_games: int
    stream_games: int
    static_value: float
    stream_value: float
    adds: list[str] = field(default_factory=list)

    @property
    def extra_games(self) -> int:
        return self.stream_games - self.static_games

    @property
    def extra_value(self) -> float:
        return self.stream_value - self.static_value


@dataclass
class BacktestResult:
    team_name: str
    year: int
    weeks: list[WeekResult]
    static_categories: dict[str, float]
    stream_categories: dict[str, float]
    max_adds: int
    max_add_value: float | None = None

    @property
    def total_static_games(self) -> int:
        return sum(w.static_games for w in self.weeks)

    @property
    def total_stream_games(self) -> int:
        return sum(w.stream_games for w in self.weeks)

    @property
    def total_extra_games(self) -> int:
        return self.total_stream_games - self.total_static_games

    @property
    def total_adds(self) -> int:
        return sum(len(w.adds) for w in self.weeks)


def _player_avg(player, year: int) -> dict:
    return player.stats.get(f"{year}_total", {}).get("avg") or {}


def accumulate_categories(plan: WeeklyPlan, year: int, totals: dict[str, float]) -> None:
    """Add each started player's season-average counting stats into ``totals``."""
    for assigns in plan.by_day.values():
        for player, _slot in assigns:
            avg = _player_avg(player, year)
            for cat in COUNTING_CATS:
                totals[cat] += float(avg.get(cat, 0) or 0)


def greedy_stream(
    roster: list,
    free_agents: list,
    days: list[int],
    slot_counts: dict[str, int],
    values: dict,
    *,
    max_adds: int,
    min_value: float,
    lock_value: float,
    games_weight: float,
) -> tuple[WeeklyPlan, list]:
    """Apply up to ``max_adds`` best add/drop swaps sequentially, then return the plan.

    Returns the optimized weekly plan for the streamed roster and the list of added players.
    """
    current = list(roster)
    used: set = set()
    adds: list = []
    for _ in range(max_adds):
        pool = [fa for fa in free_agents if getattr(fa, "playerId", None) not in used]
        moves = recommend_streams(
            current, pool, days, slot_counts, values,
            min_value=min_value, lock_value=lock_value, max_moves=1, games_weight=games_weight,
        )
        if not moves:
            break
        move = moves[0]
        current = [p for p in current if p is not move.drop] + [move.add]
        used.add(getattr(move.add, "playerId", None))
        adds.append(move.add)
    return weekly_plan(current, days, slot_counts, values, games_weight), adds


def run_backtest(
    config: Config,
    *,
    use_cache: bool = True,
    from_week: int = 1,
    to_week: int | None = None,
    max_adds: int = 3,
    proj_weight: float | None = None,
    max_add_value: float | None = None,
) -> BacktestResult:
    """Replay the configured season week-by-week comparing static vs streamed lineups.

    ``max_add_value`` caps the 8-cat value of streaming candidates, so the backtest can be
    restricted to realistic waiver-wire adds rather than stars that happen to sit in the
    finished season's free-agent pool. ``None`` uses the whole pool (theoretical ceiling).
    """
    client = EspnClient(config, use_cache=use_cache)
    team = resolve_team(client, config)
    roster = list(team.roster)
    free_agents = client.free_agents()
    slot_counts = client.roster_slots() or dict(DEFAULT_STARTING_SLOTS)

    pw = config.proj_weight if proj_weight is None else proj_weight
    pool = dedupe_players(roster + free_agents)
    values_df = value_players(pool, pw, config.year)
    values = dict(zip(values_df["player_id"], values_df["value"]))

    candidates = free_agents
    if max_add_value is not None:
        candidates = [fa for fa in free_agents if values.get(fa.playerId, 0.0) <= max_add_value]

    all_weeks = sorted(client.league.matchup_ids.keys())
    last = to_week if to_week is not None else (all_weeks[-1] if all_weeks else 0)
    weeks: list[WeekResult] = []
    static_cats = {c: 0.0 for c in COUNTING_CATS}
    stream_cats = {c: 0.0 for c in COUNTING_CATS}

    for mp in all_weeks:
        if mp < from_week or mp > last:
            continue
        days = client.matchup_scoring_periods(mp)
        if not days:
            continue
        static = weekly_plan(roster, days, slot_counts, values, config.games_weight)
        streamed, adds = greedy_stream(
            roster, candidates, days, slot_counts, values,
            max_adds=max_adds, min_value=config.min_value,
            lock_value=config.lock_value, games_weight=config.games_weight,
        )
        accumulate_categories(static, config.year, static_cats)
        accumulate_categories(streamed, config.year, stream_cats)
        weeks.append(WeekResult(
            matchup_period=mp, days=len(days),
            static_games=static.games, stream_games=streamed.games,
            static_value=static.value, stream_value=streamed.value,
            adds=[p.name for p in adds],
        ))

    return BacktestResult(
        team_name=team.team_name, year=config.year, weeks=weeks,
        static_categories=static_cats, stream_categories=stream_cats,
        max_adds=max_adds, max_add_value=max_add_value,
    )
