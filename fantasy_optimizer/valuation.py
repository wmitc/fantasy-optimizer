"""8-category z-score valuation for ESPN fantasy basketball.

Each player gets a single ``value`` = sum of per-category z-scores across an 8-cat league
(PTS, REB, AST, STL, BLK, 3PM, FG%, FT% -- turnovers excluded). Percentage categories are
**volume-weighted** so a 90% free-throw shooter on two attempts doesn't outrank a 85%
shooter on ten. Each player's stat line is a blend of ESPN projections and season-to-date
actuals controlled by ``proj_weight``.

The math (:func:`value_lines`) operates on plain dicts so it is easy to unit-test; the
ESPN-object plumbing (:func:`blended_lines`, :func:`value_players`) sits on top.
"""

from __future__ import annotations

import pandas as pd

# Raw per-game stats we need: the six counting cats plus makes/attempts for the % cats.
COUNTING_CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM"]
_PCT_INPUTS = ["FGM", "FGA", "FTM", "FTA"]
RAW_STATS = COUNTING_CATS + _PCT_INPUTS

# Category columns that make up the 8-cat total value.
VALUE_CATS = COUNTING_CATS + ["FG%", "FT%"]


def _avg_dict(player, kind: str, year: int) -> dict:
    """Return a player's per-game average dict for ``kind`` in {'total', 'projected'}."""
    split = player.stats.get(f"{year}_{kind}", {}) if getattr(player, "stats", None) else {}
    return split.get("avg") or {}


def _blend_stat(actual: dict, projected: dict, stat: str, proj_weight: float) -> float:
    """Blend one stat, falling back to whichever source is present."""
    a = actual.get(stat)
    p = projected.get(stat)
    if a is None and p is None:
        return 0.0
    if a is None:
        return float(p)
    if p is None:
        return float(a)
    return proj_weight * float(p) + (1.0 - proj_weight) * float(a)


def blended_lines(players, proj_weight: float, year: int) -> list[dict]:
    """Build blended per-game stat lines for a list of espn-api ``Player`` objects."""
    lines: list[dict] = []
    for player in players:
        actual = _avg_dict(player, "total", year)
        projected = _avg_dict(player, "projected", year)
        line = {stat: _blend_stat(actual, projected, stat, proj_weight) for stat in RAW_STATS}
        line["name"] = player.name
        line["player_id"] = player.playerId
        line["proTeam"] = getattr(player, "proTeam", None)
        line["player"] = player
        lines.append(line)
    return lines


def value_lines(lines: list[dict]) -> pd.DataFrame:
    """Compute 8-cat z-scores and total value for a list of blended stat lines.

    Returns a DataFrame with one row per line: the raw stats, ``FG%``/``FT%``, a
    ``z_<CAT>`` column per category, and a summed ``value`` column, sorted descending.
    """
    if not lines:
        return pd.DataFrame(columns=[*RAW_STATS, "FG%", "FT%", *[f"z_{c}" for c in VALUE_CATS], "value"])

    df = pd.DataFrame(lines)
    for stat in RAW_STATS:
        if stat not in df:
            df[stat] = 0.0
        df[stat] = df[stat].fillna(0.0).astype(float)

    # Per-player percentages from blended makes/attempts (0 attempts -> 0%).
    df["FG%"] = (df["FGM"] / df["FGA"].where(df["FGA"] > 0)).fillna(0.0)
    df["FT%"] = (df["FTM"] / df["FTA"].where(df["FTA"] > 0)).fillna(0.0)

    # Counting categories: plain z-score across the pool.
    for cat in COUNTING_CATS:
        df[f"z_{cat}"] = _zscore(df[cat])

    # Percentage categories: volume-weighted impact, then z-scored.
    df["z_FG%"] = _zscore(_pct_impact(df["FG%"], df["FGM"], df["FGA"]))
    df["z_FT%"] = _zscore(_pct_impact(df["FT%"], df["FTM"], df["FTA"]))

    df["value"] = df[[f"z_{c}" for c in VALUE_CATS]].sum(axis=1)
    return df.sort_values("value", ascending=False).reset_index(drop=True)


def value_players(players, proj_weight: float, year: int) -> pd.DataFrame:
    """End-to-end: blend espn-api ``Player`` lines then compute 8-cat values."""
    return value_lines(blended_lines(players, proj_weight, year))


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _pct_impact(pct: pd.Series, makes: pd.Series, attempts: pd.Series) -> pd.Series:
    """Volume-weighted impact of a percentage category.

    Uses the pool's attempt-weighted mean percentage as the baseline, then weights each
    player's deviation from it by their attempt volume -- the standard way to value FG%/FT%
    so high-volume shooters move the needle more than low-volume ones.
    """
    total_attempts = attempts.sum()
    league_pct = makes.sum() / total_attempts if total_attempts > 0 else 0.0
    return (pct - league_pct) * attempts
