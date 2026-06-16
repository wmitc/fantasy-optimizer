"""Unit tests for the 8-cat z-score valuation engine."""

from __future__ import annotations

import math

from fantasy_optimizer.valuation import (
    VALUE_CATS,
    blended_lines,
    value_lines,
    value_players,
)


def _line(name, **stats):
    base = dict(PTS=0, REB=0, AST=0, STL=0, BLK=0, **{"3PM": 0}, FGM=0, FGA=0, FTM=0, FTA=0)
    base.update(stats)
    base["name"] = name
    base["player_id"] = name
    return base


def test_empty_lines_returns_empty_frame():
    df = value_lines([])
    assert df.empty
    assert "value" in df.columns


def test_counting_category_zscores_order_and_center():
    lines = [
        _line("hi", PTS=30),
        _line("mid", PTS=20),
        _line("lo", PTS=10),
    ]
    df = value_lines(lines).set_index("name")
    # Higher points -> higher z and higher total value.
    assert df.loc["hi", "z_PTS"] > df.loc["mid", "z_PTS"] > df.loc["lo", "z_PTS"]
    assert df.loc["hi", "value"] > df.loc["lo", "value"]
    # Population z-scores are centered on zero.
    assert math.isclose(df["z_PTS"].mean(), 0.0, abs_tol=1e-9)


def test_zero_variance_category_contributes_zero():
    lines = [_line("a", REB=5), _line("b", REB=5), _line("c", REB=5)]
    df = value_lines(lines)
    assert (df["z_REB"] == 0).all()


def test_percentage_categories_are_volume_weighted():
    # Same FG% (.60) but very different volume; identical everything else.
    lines = [
        _line("highvol", FGM=12, FGA=20),
        _line("lowvol", FGM=1.2, FGA=2),
        _line("badvol", FGM=8, FGA=20),
    ]
    df = value_lines(lines).set_index("name")
    # Equal percentage, higher volume -> higher FG% impact than the low-volume player.
    assert df.loc["highvol", "z_FG%"] > df.loc["lowvol", "z_FG%"]
    # A high-volume below-average shooter is penalized most.
    assert df.loc["badvol", "z_FG%"] < df.loc["lowvol", "z_FG%"]


def test_value_is_sum_of_category_zscores():
    lines = [
        _line("a", PTS=25, REB=8, AST=5, STL=2, BLK=1, **{"3PM": 3}, FGM=9, FGA=16, FTM=5, FTA=6),
        _line("b", PTS=10, REB=12, AST=2, STL=1, BLK=2, **{"3PM": 1}, FGM=4, FGA=9, FTM=2, FTA=4),
        _line("c", PTS=18, REB=4, AST=9, STL=1, BLK=0, **{"3PM": 2}, FGM=7, FGA=15, FTM=4, FTA=5),
    ]
    df = value_lines(lines)
    expected = df[[f"z_{c}" for c in VALUE_CATS]].sum(axis=1)
    assert (df["value"] - expected).abs().max() < 1e-9


# --- blended_lines (espn-api object adapter) ---------------------------------


class _FakePlayer:
    def __init__(self, name, year, total=None, projected=None):
        self.name = name
        self.playerId = name
        self.proTeam = "BOS"
        self.stats = {}
        if total is not None:
            self.stats[f"{year}_total"] = {"avg": total}
        if projected is not None:
            self.stats[f"{year}_projected"] = {"avg": projected}


def test_blend_respects_proj_weight():
    year = 2026
    p = _FakePlayer("x", year, total={"PTS": 10}, projected={"PTS": 20})
    line = blended_lines([p], proj_weight=0.25, year=year)[0]
    # 0.25 * 20 + 0.75 * 10 = 12.5
    assert math.isclose(line["PTS"], 12.5)


def test_blend_falls_back_when_one_source_missing():
    year = 2026
    only_proj = _FakePlayer("p", year, projected={"PTS": 18})
    only_actual = _FakePlayer("a", year, total={"PTS": 14})
    lp = blended_lines([only_proj], proj_weight=0.5, year=year)[0]
    la = blended_lines([only_actual], proj_weight=0.5, year=year)[0]
    assert math.isclose(lp["PTS"], 18.0)  # no actuals -> use projection
    assert math.isclose(la["PTS"], 14.0)  # no projection -> use actuals


def test_value_players_end_to_end_with_fake_objects():
    year = 2026
    players = [
        _FakePlayer("star", year, total={"PTS": 28, "REB": 9, "AST": 7, "FGM": 10, "FGA": 18, "FTM": 7, "FTA": 8}),
        _FakePlayer("scrub", year, total={"PTS": 4, "REB": 2, "AST": 1, "FGM": 1, "FGA": 5, "FTM": 1, "FTA": 2}),
    ]
    df = value_players(players, proj_weight=0.0, year=year)
    assert list(df["name"]) == ["star", "scrub"]
    assert df.iloc[0]["value"] > df.iloc[1]["value"]
