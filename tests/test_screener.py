"""The stock screener: point-in-time fundamentals, the models' rules, the history (ADR-136)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab import screener
from eulerlab.backtest import screener_models as sm
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.fundamentals import annual


def _year(fy: date, **v: float) -> annual.Year:
    return annual.Year("INE1", "ABC", fy, annual.known_from(fy), "2026-10-18", dict(v))


def test_a_year_counts_from_90_days_after_its_end_and_2020_from_august() -> None:
    assert annual.known_from(date(2023, 3, 31)) == date(2023, 6, 29)
    assert annual.known_from(date(2020, 3, 31)) == date(2020, 8, 1)
    years = [
        _year(date(2022, 3, 31), net_profit=1, total_assets=2),
        _year(date(2023, 3, 31), net_profit=1, total_assets=2),
    ]
    assert [y.fy_end.year for y in annual.known(years, date(2023, 6, 28))] == [2022]
    assert [y.fy_end.year for y in annual.known(years, date(2023, 6, 29))] == [2022, 2023]


def test_snapshot_rows_become_years_and_the_table_joins_on_isin(tmp_path: Path) -> None:
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    records = [
        {
            "symbol": "ABC",
            "section": "profit-loss",
            "row_label": "Net Profit",
            "period": "2024-03-31",
            "value": 10.0,
        },
        {
            "symbol": "ABC",
            "section": "balance-sheet",
            "row_label": "Total Assets",
            "period": "2024-03-31",
            "value": 100.0,
        },
        {
            "symbol": "ABC",
            "section": "profit-loss",
            "row_label": "Net Profit",
            "period": "TTM",
            "value": 12.0,
        },
        {"symbol": "ABC", "section": "top_ratios", "row_label": "ROE", "period": "", "value": 9.0},
    ]
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(records), buf)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "symbol": "ABC",
                "fetch_date": "2026-10-18",
                "path": "ABC/x.parquet",
                "consolidated": True,
            }
        )
        + "\n"
        + json.dumps(
            {
                "symbol": "OLD",
                "fetch_date": "2026-10-18",
                "path": "OLD/x.parquet",
                "consolidated": True,
            }
        )
        + "\n"
    )
    out, meta = tmp_path / "a.jsonl", tmp_path / "m.json"
    reads: list[str] = []

    def read(rel: str) -> bytes:
        reads.append(rel)
        return buf.getvalue()

    got = annual.build({"ABC": "INE1"}, read=read, manifest=manifest, out=out, meta=meta)
    assert got == {"companies": 1, "years": 1, "read": 1, "no_isin": 1, "failed": 0}
    table = annual.load(out)
    assert (
        table["INE1"][0].known_from == date(2024, 6, 29)
        and table["INE1"][0].get("net_profit") == 10.0
    )
    annual.build({"ABC": "INE1"}, read=read, manifest=manifest, out=out, meta=meta)
    assert reads == ["ABC/x.parquet"]  # unchanged snapshot: not read again


def test_fscore_counts_eight_signals() -> None:
    p = _year(
        date(2023, 3, 31),
        net_profit=5,
        total_assets=100,
        borrowings=30,
        op_profit=10,
        sales=80,
        equity_capital=10,
        cfo=4,
    )
    y = _year(
        date(2024, 3, 31),
        net_profit=8,
        total_assets=100,
        borrowings=20,
        op_profit=15,
        sales=90,
        equity_capital=10,
        cfo=9,
    )
    assert sm.fscore(y, p) == 8
    worse = _year(
        date(2024, 3, 31),
        net_profit=-1,
        total_assets=100,
        borrowings=40,
        op_profit=5,
        sales=70,
        equity_capital=12,
        cfo=-2,
    )
    assert sm.fscore(worse, p) == 0


def test_per_share_values_are_put_into_the_decision_dates_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 10-for-1 split on 2022-07-28: EPS shown today in post-split units is 10x too small for 2021.
    monkeypatch.setattr(sm, "_factors", lambda: {"INE1": ([date(2022, 7, 28)], [10.0, 1.0])})
    assert sm.units("INE1", date(2021, 9, 1)) == 10.0
    assert sm.units("INE1", date(2022, 8, 1)) == 1.0
    assert sm.units("OTHER", date(2021, 9, 1)) == 1.0


def _rows(
    closes: list[float], volumes: list[float] | None = None, symbol: str = "ABC"
) -> list[PanelRow]:
    start = date(2020, 1, 1)
    vols = volumes or [1e6] * len(closes)
    return [
        PanelRow(
            day=start + timedelta(days=i),
            symbol=symbol,
            close=c,
            volume=v,
            turnover=c * v,
            isin="INE1",
        )
        for i, (c, v) in enumerate(zip(closes, vols, strict=True))
    ]


def test_the_pullback_is_held_after_an_oversold_dip_in_an_uptrend_until_rsi_recovers() -> None:
    up = [100 + i * 0.5 for i in range(230)]
    dip = [*up, up[-1] - 4, up[-1] - 8]
    strat = sm.TrendPullback()
    assert strat.held(_rows(dip))
    recovered = [*dip, dip[-1] + 6, dip[-1] + 12]
    assert not strat.held(_rows(recovered))
    down = [200 - i * 0.5 for i in range(230)] + [80, 76]
    assert not strat.held(_rows(down))
    assert strat.rebalance_every == 5 and sm.BreakoutVolume().rebalance_every == 5
    assert sm.QualityMomentum().rebalance_every == 21


def test_a_breakout_needs_a_new_high_and_twice_the_usual_volume() -> None:
    closes = [100.0] * 260 + [105.0]
    rows = _rows(closes, [1e6] * 260 + [2.5e6])
    assert sm.BreakoutVolume.breakout(rows, len(rows) - 1)
    quiet = _rows(closes, [1e6] * 261)
    assert not sm.BreakoutVolume.breakout(quiet, len(quiet) - 1)


def test_the_adjusted_view_matches_the_engines_rule() -> None:
    rows = _rows([200.0, 202.0, 20.4, 20.6])  # 10-for-1 split ex on day 3
    events = {"INE1": [(rows[2].day, 10.0)]}
    before = screener.adjusted_view({"ABC": rows}, rows[1].day, 10, events)
    after = screener.adjusted_view({"ABC": rows}, rows[3].day, 10, events)
    assert [r.close for r in before.history["ABC"]] == [200.0, 202.0]  # the split is not known yet
    assert [round(r.close, 2) for r in after.history["ABC"]] == [20.0, 20.2, 20.4, 20.6]


def _view(series: dict[str, list[float]]) -> MarketView:
    return MarketView(
        as_of=_rows(next(iter(series.values())))[-1].day,
        history={s: _rows(c, symbol=s) for s, c in series.items()},
    )


def test_history_records_once_and_scores_from_the_next_close_against_nifty(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    now = datetime(2026, 11, 4, tzinfo=UTC)
    lists: list[dict[str, Any]] = [
        {"id": "m", "kind": "swing", "picks": ["AAA", "BBB"], "error": ""},
        {"id": "broken", "kind": "long", "picks": [], "error": "x"},
    ]
    assert screener.record(lists, "2020-01-01", now, path) == 1
    assert screener.record(lists, "2020-01-01", now, path) == 0
    view = _view(
        {
            "NIFTYBEES": [100, 100, 101, 102, 103, 104, 105, 106],
            "AAA": [50, 50, 55, 55, 55, 55, 60, 60],
            "BBB": [10, 10, 10, 10, 10, 10, 9, 9],
        }
    )
    got = screener.track(view, screener.history(path))["m"]
    sel = got["selections"][0]
    # Filled at the next close (day 1), held 5 sessions to day 6.
    assert sel["from"] == "2020-01-02" and sel["to"] == "2020-01-07" and sel["complete"]
    assert sel["return"] == round((60 / 50 - 1 + 9 / 10 - 1) / 2, 4)
    assert sel["nifty"] == round(105 / 100 - 1, 4) and sel["beat_nifty"] == 0.5
    assert got["complete"] == 1 and got["mean_excess"] == sel["excess"]


def test_the_swing_blend_is_chosen_by_its_worse_half_not_its_best_result() -> None:
    cfg = {"main_long": "L", "swing_candidates": ["A", "B", "C"], "robust_floor": 0.5}
    lists: list[dict[str, Any]] = [
        {"id": "L", "kind": "long", "parts": [1, 2]},
        {"id": "A", "kind": "swing", "parts": [1, 2]},
        {"id": "B", "kind": "swing", "parts": [1, 2]},
        {"id": "C", "kind": "swing", "parts": [1, 2, 3]},
    ]
    # A has the best single half (2.0) but a weak other half; B is steadier.
    halves = [
        {"A": {"sharpe": 2.0}, "B": {"sharpe": 0.9}, "C": {"sharpe": 0.9}},
        {"A": {"sharpe": 0.3}, "B": {"sharpe": 0.8}, "C": {"sharpe": 0.8}},
    ]
    got = screener.choose(lists, cfg, halves)
    assert got["chosen_swing"] == "B"  # tie with C on the worse half goes to fewer parts
    assert [x["id"] for x in lists][:2] == ["L", "B"]
    assert next(x for x in lists if x["id"] == "A")["halves"] == [2.0, 0.3]
    weak = [{"A": {"sharpe": 0.4}, "B": {"sharpe": 0.4}, "C": {"sharpe": 0.4}}] * 2
    assert screener.choose(lists, cfg, weak)["chosen_swing"] == ""
    assert screener.choose(lists, cfg, [])["why"] == "the half-period runs are not held yet"


def test_a_blend_adds_its_parts_weights_at_fixed_shares() -> None:
    class Fixed(Strategy):
        lookback = 1

        def __init__(self, w: dict[str, float]) -> None:
            self.name, self.w = "fixed", w

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return self.w

    blend = sm.Blend.__new__(sm.Blend)
    blend.name, blend.rebalance_every, blend.lookback = "b", 21, 1
    blend.parts = [(Fixed({"AAA": 0.5, "BBB": 0.5}), 0.7), (Fixed({"BBB": 1.0}), 0.3)]
    view = _view({"AAA": [1.0, 1.0], "BBB": [1.0, 1.0]})
    got = blend.target_weights(view)
    assert got == pytest.approx({"AAA": 0.35, "BBB": 0.65})
    built = sm.BUILDERS["screen_long_blend"]()
    assert isinstance(built, sm.Blend)
    assert [round(s, 2) for _, s in built.parts] == [0.7, 0.3] and built.rebalance_every == 21
    assert {k: sm.KIND[k] for k in sm.KIND if k.startswith("screen_swing_")} == dict.fromkeys(
        ["screen_swing_mom_weinstein", "screen_swing_breakout_weinstein", "screen_swing_three"],
        "swing",
    )


def test_the_consensus_holds_what_three_parts_agree_on() -> None:
    class Fixed(Strategy):
        lookback = 1

        def __init__(self, names: list[str]) -> None:
            self.name = "fixed"
            self.names = names

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return dict.fromkeys(self.names, 1.0 / len(self.names))

    c = sm.Consensus.__new__(sm.Consensus)
    c.name, c.min_votes, c.rebalance_every, c.lookback = "c", 3, 21, 1
    c.parts = [
        ("p1", Fixed(["AAA", "BBB", "CCC"])),
        ("p2", Fixed(["AAA", "BBB"])),
        ("p3", Fixed(["AAA", "CCC"])),
        ("p4", Fixed(["BBB", "DDD"])),
        ("p5", Fixed(["EEE"])),
    ]
    view = _view({s: [1.0, 1.0] for s in ("AAA", "BBB", "CCC", "DDD", "EEE")})
    assert c.votes(view) == {"AAA": 3, "BBB": 3, "CCC": 2, "DDD": 1, "EEE": 1}
    assert c.target_weights(view) == {"AAA": 0.5, "BBB": 0.5}
    built = sm.BUILDERS["screen_consensus_3of5"]()
    assert isinstance(built, sm.Consensus) and [p for p, _ in built.parts] == list(
        sm.CONSENSUS_PARTS
    )
    assert built.min_votes == 3 and built.rebalance_every == 21
    assert sm.KIND["screen_consensus_3of5"] == "long"
