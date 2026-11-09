"""Top-down screening: sector tags, the sector and industry ranking, the capped pick (research 182)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.backtest import screener_models as sm
from eulerlab.backtest import topdown
from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow
from eulerlab.fundamentals import sectors

START = date(2024, 1, 1)


def _rows(symbol: str, growth: float, n: int = 140) -> list[PanelRow]:
    return [
        PanelRow(
            day=START + timedelta(days=i),
            symbol=symbol,
            close=100.0 * (1 + growth) ** i,
            volume=1e5,
            turnover=1e7,
            isin=f"IN-{symbol}",
        )
        for i in range(n)
    ]


def _tag(symbol: str, sector: str, industry: str) -> sectors.Tag:
    return sectors.Tag(symbol, "Broad", sector, industry, "")


def test_a_snapshot_tag_is_read_from_its_sector_rows() -> None:
    records = [
        {"section": "sector", "row_label": "level_1", "raw": "Industrials"},
        {"section": "sector", "row_label": "level_2", "raw": "Capital Goods"},
        {"section": "sector", "row_label": "level_3", "raw": "Electrical Equipment"},
        {"section": "quarters", "row_label": "Sales", "raw": "1,000"},
    ]
    tag = sectors.tag_from_records("ABB", records)
    assert tag == sectors.Tag("ABB", "Industrials", "Capital Goods", "Electrical Equipment", "")
    assert sectors.tag_from_records("X", [{"section": "quarters", "row_label": "Sales"}]) is None


def test_the_ranking_keeps_the_strongest_sectors_and_needs_three_members() -> None:
    # Sector A rises fastest, B next; C has only two members and is not scored.
    growth = {"A1": 0.004, "A2": 0.004, "A3": 0.004, "B1": 0.002, "B2": 0.002, "B3": 0.002}
    growth |= {"C1": 0.01, "C2": 0.01, "D1": -0.001, "D2": -0.001, "D3": -0.001}
    history = {s: _rows(s, g) for s, g in growth.items()}
    tags = {f"IN-{s}": _tag(s, s[0], f"{s[0]}-ind") for s in growth}
    view = MarketView(as_of=history["A1"][-1].day, history=history)
    rk = topdown.rank(view, list(growth), tags, top=2)
    assert rk.top_sectors == ("A", "B")
    assert "C" not in rk.sector_score
    assert rk.passes("A1") and not rk.in_top_sectors("D1")
    # C's industry has two members: it inherits nothing, since C itself is unscored.
    assert "C / C-ind" not in rk.industry_score


def test_a_small_industry_inherits_its_sectors_score() -> None:
    growth = {"A1": 0.004, "A2": 0.004, "A3": 0.004, "A4": 0.003}
    history = {s: _rows(s, g) for s, g in growth.items()}
    tags = {f"IN-{s}": _tag(s, "A", "big" if s != "A4" else "small") for s in growth}
    view = MarketView(as_of=history["A1"][-1].day, history=history)
    rk = topdown.rank(view, list(growth), tags)
    assert rk.industry_score["A / small"] == rk.sector_score["A"]


def test_the_pick_takes_at_most_cap_from_one_sector() -> None:
    scores = {f"S{i}": float(10 - i) for i in range(10)}
    sector_of = {f"S{i}": "X" if i < 8 else "Y" for i in range(10)}
    got = sm._capped(scores, sector_of, n=5, cap=3)
    assert sorted(got) == ["S0", "S1", "S2", "S8", "S9"]
    assert abs(sum(got.values()) - 1.0) < 1e-12


def test_cheapness_is_measured_against_industry_peers() -> None:
    rk = topdown.Ranking(
        sector_of=dict.fromkeys(["a", "b", "c", "d"], "S"),
        industry_of={"a": "S / i", "b": "S / i", "c": "S / i", "d": "S / j"},
        sector_score={"S": 0.1},
        industry_score={"S / i": 0.1, "S / j": 0.1},
        top_sectors=("S",),
        strong_industries=frozenset({"S / i", "S / j"}),
    )
    rel = sm.industry_relative({"a": 0.10, "b": 0.05, "c": 0.02, "d": 0.08}, rk)
    assert rel["a"] == 0.10 - 0.05 and rel["c"] == 0.02 - 0.05
    # d's industry has one member, so it is judged against the sector's median.
    assert abs(rel["d"] - (0.08 - 0.065)) < 1e-12


def test_the_top_down_models_are_registered_with_their_kinds() -> None:
    for sid, kind in (
        ("screen_topdown_sectors", sm.LONG),
        ("screen_topdown_quality_momentum", sm.LONG),
        ("screen_topdown_discount", sm.LONG),
        ("screen_topdown_pullback", sm.SWING),
        ("screen_topdown_breakout", sm.SWING),
    ):
        assert sm.KIND[sid] == kind
        assert sm.BUILDERS[sid]().name == sid
