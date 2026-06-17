# fantasy-optimizer

Streamer pick optimization tool for Fantasy Men's Basketball on espn.com.

The premise: *streaming wins matchups.* In head-to-head 8-category leagues you maximize
total **games played** each scoring week by routinely swapping marginal players, while
keeping a quality starting lineup. This CLI pulls fresh data via
[`espn-api`](https://github.com/cwendt94/espn-api), values the waiver-wire pool, and
recommends the best add/drop moves and a day-by-day lineup.

## What it does

- Pulls your roster, league settings, and the free-agent pool from ESPN.
- Values every player with an **8-cat z-score** model (PTS, REB, AST, STL, BLK, 3PM, FG%, FT%),
  blending ESPN projections with season-to-date actuals. FG%/FT% are volume-weighted.
- Maps the current scoring week into days and counts each player's games per day.
- Optimizes a **day-by-day lineup** (max-weight assignment of players to starting slots)
  that maximizes games played by good players, and ranks the **top streaming add/drop
  moves** by how much each raises your projected weekly value.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml      # then fill in league id, cookies, and your team
fantasy-optimizer recommend             # or: python -m fantasy_optimizer.cli recommend
```

## Configuration

Settings come from `config.toml` (gitignored) with environment-variable overrides; a `.env`
file is loaded automatically. See `config.example.toml` for the full annotated list.

- `league_id`, `year` — from your ESPN league URL (use the season's **end** year).
- `espn_s2`, `swid` — browser cookies, required for private leagues. Log in to
  fantasy.espn.com, open DevTools → Application → Cookies, and copy both values.
- `team_id` / `team_name` — which team is yours. If unset, the tool tries to match you via
  the SWID owner id, and otherwise prints the team list so you can choose.
- Valuation/streaming knobs: `proj_weight`, `pool_size`, `min_value`, `lock_value`,
  `games_weight`.

Starting-lineup slots are **auto-detected** from your league. This league runs
1 PG, 1 SG, 1 SF, 1 PF, 1 C, 1 G, 1 F, 3 UTIL (10 active) + 4 bench + 1 IR.

## Usage

```bash
fantasy-optimizer recommend                 # current week, cached data
fantasy-optimizer recommend --explain       # show per-category z-scores
fantasy-optimizer recommend --days 3        # only the next 3 days
fantasy-optimizer recommend --no-cache      # force a fresh ESPN pull
fantasy-optimizer recommend --proj-weight 0.7   # trust projections more
```

Output sections: a plan header (games & value for the week), a per-day optimal lineup,
the top streaming moves (add → drop with the value gain), an injured/IR panel, and the
top free agents by value.

## Backtest (off-season simulation)

Quantify how much streaming would have helped over a **completed** season (ESPN keeps full
schedules and season stats, so this works in the off-season):

```bash
fantasy-optimizer simulate --max-adds 3 --max-add-value 3.0   # realistic waiver adds
fantasy-optimizer simulate --max-adds 3                       # theoretical ceiling (whole FA pool)
```

It replays each scoring week and compares **set-and-forget** vs. **streaming** (greedily
adding up to `--max-adds` free agents per week to fill schedule gaps), reporting extra games
played and counting-stat production. `--max-add-value` caps streamer value so you compare
against genuine waiver-wire players rather than stars sitting in a finished league's FA pool.

Fidelity caveats: a finished season only exposes each team's *final* roster, FA pool, and
injury statuses (used as proxies for every historical week), and production is modeled as the
**season average per scheduled game**, not the literal box score. So it measures the
*opportunity* streaming creates given real schedules, not a move-by-move replay.

### Example results

Backtest of one team (**Monstars**) over the full 2025-26 season, streaming up to 3 waiver
pickups per week capped at replacement-level value (`--max-adds 3 --max-add-value 3.0`).
That team finished **2nd (runner-up)** in the 12-team league with a 73–53–2 category record —
real-world validation that aggressive streaming for games is a winning approach:

| Strategy | Games | PTS | REB | AST | STL | BLK | 3PM |
|----------|------:|------:|------:|------:|----:|----:|------:|
| Set-and-forget | 598 | 8,884 | 3,103 | 2,103 | 560 | 320 | 862 |
| Streaming | **843** | 10,981 | 4,157 | 2,487 | 698 | 474 | 1,135 |
| **Gain** | **+245** | +2,097 | +1,054 | +384 | +138 | +154 | +273 |

That's **+245 games over the season (~13 per week across 57 adds)** — concrete evidence that
streaming for games meaningfully boosts counting-stat production. Running without
`--max-add-value` shows a much higher *theoretical* ceiling, but it "streams" stars that
would never realistically clear waivers, so the capped run is the honest number.

#### Per-week picture (regular season)

Because H2H is won or lost **each week independently**, the weekly matchup is the right unit
to judge streaming. The full-season totals above are skewed by the playoff/All-Star periods
(weeks 17–19 span 14–21 days each), so restricting to the **regular-season weekly matchups**
(`--to-week 16`, all 6–7 days) gives a cleaner read:

| | Total | Per week (avg) |
|---|------:|------:|
| Set-and-forget games | 424 | ~26.5 |
| Streaming games | **601** | **~37.6** |
| **Extra games** | **+177** | **~+11.1** |

Key takeaways:

- **~+42% more player-games per matchup**, turning a ~26–27 game baseline into ~38.
- **Consistent, not outlier-driven** — every single week lands between **+8 and +12** extra
  games. Even the short All-Star-break week (only 14 baseline games) still gained +8.
- The picks are genuine waiver-wire players (e.g. Jaylon Tyson, Malcolm Brogdon, Al Horford,
  Dillon Brooks, Obi Toppin, Robert Williams III), not stars — so the edge is realistic.

~11 extra player-games every week is a large, repeatable volume advantage across all six
counting categories — the core argument for streaming.

## Tuning

- **`proj_weight`** (0–1): higher leans on ESPN projections, lower on season actuals. Early
  season, raise it; late season, lower it.
- **`games_weight`**: a per-started-game bonus. `0` benches below-replacement players;
  raise it to chase volume and field marginal players on open days.
- **`lock_value`**: roster players at/above this 8-cat value are never suggested as drops.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
