"""Command-line interface: print streaming recommendations as rich tables."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import load_config
from .optimizer import NON_STARTING_SLOTS
from .recommend import Recommendation, build_recommendation
from .schedule import player_game_days, player_opponent
from .simulate import BacktestResult, run_backtest
from .valuation import COUNTING_CATS

_SLOT_ORDER = ["PG", "SG", "SF", "PF", "C", "G", "F", "UT"]
_CORE_POS = ["PG", "SG", "SF", "PF", "C"]


def _day_date(day: int, players: list) -> datetime | None:
    for p in players:
        entry = getattr(p, "schedule", {}).get(str(day))
        if entry and entry.get("date"):
            return entry["date"]
    return None


def _fmt_day(day: int, date: datetime | None) -> str:
    return date.strftime("%a %m/%d") if date else f"SP{day}"


def _positions(player) -> str:
    return "/".join(s for s in getattr(player, "eligibleSlots", []) if s in _CORE_POS)


def _render(rec: Recommendation, console: Console, *, top: int, explain: bool) -> None:
    pool = rec.roster + rec.free_agents

    header = (
        f"[bold]{rec.team.team_name}[/bold]  ·  matchup period {rec.matchup_period}\n"
        f"Days remaining: {len(rec.remaining_days)} of {len(rec.week_days)}  ·  "
        f"Projected games: [bold]{rec.plan.games}[/bold]  ·  "
        f"Projected value: [bold]{rec.plan.value:+.1f}[/bold]\n"
        f"Lineup: " + ", ".join(f"{n}×{s}" for s, n in rec.slot_counts.items() if s not in NON_STARTING_SLOTS)
    )
    console.print(Panel(header, title="Streaming plan", expand=False))

    # --- day-by-day optimal lineup ------------------------------------------
    for day in rec.remaining_days:
        date = _day_date(day, pool)
        assigns = sorted(rec.plan.by_day.get(day, []), key=lambda a: _SLOT_ORDER.index(a[1]) if a[1] in _SLOT_ORDER else 99)
        table = Table(title=f"{_fmt_day(day, date)}  ({len(assigns)} games)", title_justify="left")
        table.add_column("Slot", style="cyan")
        table.add_column("Player")
        table.add_column("Opp", style="dim")
        table.add_column("Val", justify="right")
        for player, slot in assigns:
            table.add_row(slot, player.name, player_opponent(player, day) or "-", f"{rec.values.get(player.playerId, 0):+.1f}")
        if not assigns:
            table.add_row("-", "[dim]no startable players[/dim]", "-", "-")
        console.print(table)

    # --- streaming suggestions ----------------------------------------------
    if rec.moves:
        table = Table(title="Top streaming moves (by weekly-value gain)", title_justify="left")
        table.add_column("Add", style="green")
        table.add_column("Pos", style="dim")
        table.add_column("Tm", style="dim")
        table.add_column("GP", justify="right")
        table.add_column("Val", justify="right")
        table.add_column("Drop", style="red")
        table.add_column("Val", justify="right")
        table.add_column("Gain", justify="right", style="bold")
        for m in rec.moves:
            gp = len(player_game_days(m.add, rec.remaining_days))
            table.add_row(
                m.add.name, _positions(m.add), getattr(m.add, "proTeam", "-"), str(gp),
                f"{rec.values.get(m.add.playerId, 0):+.1f}",
                m.drop.name, f"{rec.values.get(m.drop.playerId, 0):+.1f}",
                f"{m.gain:+.1f}",
            )
        console.print(table)
    else:
        console.print("[dim]No positive-gain streaming moves found for the remaining days.[/dim]")

    # --- injured / IR --------------------------------------------------------
    if rec.injured:
        names = ", ".join(f"{p.name} ({p.injuryStatus})" for p in rec.injured)
        console.print(Panel(names, title="Injured — consider IR", expand=False, border_style="yellow"))

    # --- free-agent pool -----------------------------------------------------
    fa_df = rec.values_df[rec.values_df["player_id"].isin({p.playerId for p in rec.free_agents})]
    table = Table(title=f"Top {top} free agents by value", title_justify="left")
    table.add_column("Player")
    table.add_column("Pos", style="dim")
    table.add_column("Tm", style="dim")
    table.add_column("GP", justify="right")
    table.add_column("Val", justify="right", style="bold")
    cat_cols = [c for c in fa_df.columns if c.startswith("z_")] if explain else []
    for c in cat_cols:
        table.add_column(c.replace("z_", ""), justify="right")
    for _, row in fa_df.head(top).iterrows():
        player = row["player"]
        gp = len(player_game_days(player, rec.remaining_days))
        cells = [player.name, _positions(player), getattr(player, "proTeam", "-"), str(gp), f"{row['value']:+.1f}"]
        cells += [f"{row[c]:+.1f}" for c in cat_cols]
        table.add_row(*cells)
    console.print(table)


def cmd_recommend(args: argparse.Namespace) -> int:
    console = Console()
    try:
        config = load_config(args.config)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        return 2
    if args.team_id is not None:
        config.team_id = args.team_id
    if args.team_name is not None:
        config.team_name = args.team_name

    try:
        rec = build_recommendation(
            config,
            use_cache=not args.no_cache,
            matchup_period=args.matchup,
            day_horizon=args.days,
            proj_weight=args.proj_weight,
            min_value=args.min_value,
            as_of=args.as_of,
        )
    except LookupError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    _render(rec, console, top=args.top, explain=args.explain)
    return 0


def _render_backtest(result: BacktestResult, console: Console) -> None:
    ceiling = "unbounded (theoretical)" if result.max_add_value is None else f"value ≤ {result.max_add_value:g}"
    header = (
        f"[bold]{result.team_name}[/bold]  ·  season {result.year} backtest\n"
        f"Weeks: {len(result.weeks)}  ·  max adds/week: {result.max_adds}  ·  streamer pool: {ceiling}\n"
        f"Games  —  static: [bold]{result.total_static_games}[/bold]   "
        f"streamed: [bold]{result.total_stream_games}[/bold]   "
        f"extra: [bold green]+{result.total_extra_games}[/bold green]  "
        f"(over {result.total_adds} adds)"
    )
    console.print(Panel(header, title="Season backtest: set-and-forget vs. streaming", expand=False))

    table = Table(title="Per-week games & value", title_justify="left")
    table.add_column("Wk", justify="right")
    table.add_column("Days", justify="right")
    table.add_column("Static G", justify="right")
    table.add_column("Stream G", justify="right")
    table.add_column("+G", justify="right", style="green")
    table.add_column("+Value", justify="right", style="green")
    table.add_column("Adds")
    for w in result.weeks:
        table.add_row(
            str(w.matchup_period), str(w.days), str(w.static_games), str(w.stream_games),
            f"+{w.extra_games}", f"{w.extra_value:+.0f}", ", ".join(w.adds) or "-",
        )
    console.print(table)

    cat_table = Table(title="Season counting-stat production (sum of season-avg per started game)", title_justify="left")
    cat_table.add_column("Strategy")
    for cat in COUNTING_CATS:
        cat_table.add_column(cat, justify="right")
    cat_table.add_row("static", *[f"{result.static_categories[c]:.0f}" for c in COUNTING_CATS])
    cat_table.add_row("streamed", *[f"{result.stream_categories[c]:.0f}" for c in COUNTING_CATS])
    cat_table.add_row(
        "[green]delta[/green]",
        *[f"[green]+{result.stream_categories[c] - result.static_categories[c]:.0f}[/green]" for c in COUNTING_CATS],
    )
    console.print(cat_table)

    console.print(
        "[dim]Caveats: final-season roster/FA pool/injuries are used as proxies for each "
        "historical week, and per-game production is the season average, not the actual box "
        "score. This measures the opportunity streaming creates given real schedules.[/dim]"
    )


def cmd_simulate(args: argparse.Namespace) -> int:
    console = Console()
    try:
        config = load_config(args.config)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        return 2
    if args.year is not None:
        config.year = args.year
    if args.team_id is not None:
        config.team_id = args.team_id
    if args.team_name is not None:
        config.team_name = args.team_name

    try:
        result = run_backtest(
            config,
            use_cache=not args.no_cache,
            from_week=args.from_week,
            to_week=args.to_week,
            max_adds=args.max_adds,
            proj_weight=args.proj_weight,
            max_add_value=args.max_add_value,
        )
    except LookupError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    _render_backtest(result, console)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fantasy-optimizer", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    rec = sub.add_parser("recommend", help="Recommend streaming moves and a daily lineup")
    rec.add_argument("--config", help="Path to config.toml (default: search cwd/package root)")
    rec.add_argument("--matchup", type=int, help="Matchup period (default: current)")
    rec.add_argument("--as-of", type=int, help="Plan as of this scoring-period/day (default: week start when --matchup is set, else today)")
    rec.add_argument("--days", type=int, help="Limit to the next N remaining days")
    rec.add_argument("--proj-weight", type=float, help="Override projection/actual blend weight")
    rec.add_argument("--min-value", type=float, help="Override minimum FA value to consider")
    rec.add_argument("--top", type=int, default=15, help="Free agents to list (default 15)")
    rec.add_argument("--explain", action="store_true", help="Show per-category z-scores")
    rec.add_argument("--no-cache", action="store_true", help="Bypass the on-disk API cache")
    rec.add_argument("--team-id", type=int, help="Your team id (overrides config)")
    rec.add_argument("--team-name", help="Your team name/abbrev (overrides config)")

    sim = sub.add_parser("simulate", help="Backtest set-and-forget vs. streaming over a season")
    sim.add_argument("--config", help="Path to config.toml")
    sim.add_argument("--year", type=int, help="Season to backtest (default: config year)")
    sim.add_argument("--from-week", type=int, default=1, help="First matchup period (default 1)")
    sim.add_argument("--to-week", type=int, help="Last matchup period (default: last)")
    sim.add_argument("--max-adds", type=int, default=3, help="Max waiver adds per week (default 3)")
    sim.add_argument("--max-add-value", type=float, help="Cap streamer 8-cat value (e.g. 3.0) for realistic waiver adds; default unbounded")
    sim.add_argument("--proj-weight", type=float, help="Override projection/actual blend weight")
    sim.add_argument("--no-cache", action="store_true", help="Bypass the on-disk API cache")
    sim.add_argument("--team-id", type=int, help="Your team id (overrides config)")
    sim.add_argument("--team-name", help="Your team name/abbrev (overrides config)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "simulate":
        return cmd_simulate(args)
    if args.command in (None, "recommend"):
        if args.command is None:  # default to recommend with defaults
            args = parser.parse_args(["recommend", *(argv or [])])
        return cmd_recommend(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
