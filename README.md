# fantasy-optimizer

Streamer pick optimization tool for Fantasy Men's Basketball on espn.com.

The premise: *streaming wins matchups.* In head-to-head 8-category leagues you maximize
total **games played** each scoring week by routinely swapping marginal players, while
keeping a quality starting lineup. This CLI pulls fresh data via
[`espn-api`](https://github.com/cwendt94/espn-api), values the waiver-wire pool, and
recommends the best add/drop moves and a day-by-day lineup.

> Status: in active development. See the milestone PRs for progress.

## What it does

- Pulls your roster, league settings, and the free-agent pool from ESPN.
- Values every player with an **8-cat z-score** model (PTS, REB, AST, STL, BLK, 3PM, FG%, FT%),
  blending ESPN projections with season-to-date actuals.
- Maps the current scoring week's days and counts each player's games per day.
- Recommends a day-by-day lineup that maximizes games played by good players, plus the
  top streaming add/drop moves.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml   # then fill in your league + cookies
python -m fantasy_optimizer.cli recommend
```

See `config.example.toml` for how to obtain your `espn_s2` and `SWID` cookies (required for
private leagues).

## License

MIT — see [LICENSE](LICENSE).
