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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "recommend"):
        if args.command is None:  # default to recommend with defaults
            args = parser.parse_args(["recommend", *(argv or [])])
        return cmd_recommend(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
