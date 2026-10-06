"""The strategy builder: indicators, the spec, the compiled strategy, storage.

The indicators are checked against hand-worked values, not against another
implementation of the same formula. The compiled strategy is checked for the
two properties the interface demands — the same weights from a cached replay as
from a fresh one, and the same curve from Tier A and Tier B.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from eulerlab import workspace as ws
from eulerlab.api import builder_routes
from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.strategy import MarketView
from eulerlab.builder import indicators as ind
from eulerlab.builder import store
from eulerlab.builder.compile import BuiltStrategy
from eulerlab.builder.spec import BuilderSpec, summarise
from eulerlab.builder.templates import TEMPLATES
from eulerlab.features.panel import PanelRow

START = date(2024, 1, 1)


def bar(close: float, high: float | None = None, low: float | None = None) -> ind.Bar:
    return ind.Bar(
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=1000.0,
        turnover=1e9,
    )


def feed(indicator: ind.Indicator, closes: Sequence[float]) -> list[float | None]:
    return [indicator.update(bar(c)) for c in closes]


# --- indicators, by hand --------------------------------------------------------


def test_sma_waits_for_a_full_window() -> None:
    assert feed(ind.SMA(3), [1, 2, 3, 4, 5]) == [None, None, 2.0, 3.0, 4.0]


def test_ema_is_seeded_with_the_sma() -> None:
    # alpha = 2/(3+1) = 0.5; seed mean(1,2,3) = 2; then 2 + 0.5*(4-2) = 3
    assert feed(ind.EMA(3), [1, 2, 3, 4]) == [None, None, 2.0, 3.0]


def test_rsi_uses_wilder_smoothing() -> None:
    # changes +1, -1, +1. Seed after two: gain 0.5, loss 0.5 -> 50.
    # Then gain (0.5*1 + 1)/2 = 0.75, loss (0.5*1 + 0)/2 = 0.25 -> 75.
    values = feed(ind.RSI(2), [1, 2, 1, 2])
    assert values[:2] == [None, None]
    assert values[2] == pytest.approx(50.0)
    assert values[3] == pytest.approx(75.0)


def test_rsi_of_a_series_that_only_rises_is_100() -> None:
    assert feed(ind.RSI(3), [1, 2, 3, 4, 5])[-1] == 100.0


def test_donchian_excludes_the_current_bar() -> None:
    """Otherwise "close crosses above the 20-day high" could never be true."""
    high = ind.Donchian(2, high=True)
    assert [high.update(bar(c, high=c)) for c in (1, 2, 3)] == [None, None, 2.0]


def test_roc_is_percent_change() -> None:
    assert feed(ind.ROC(1), [100, 110])[-1] == pytest.approx(10.0)


def test_atr_takes_the_widest_of_the_three_ranges() -> None:
    atr = ind.ATR(1)
    atr.update(bar(10, high=11, low=9))
    # Gap up: high-low is 1, but high - previous close is 4.
    assert atr.update(bar(13.5, high=14, low=13)) == pytest.approx(4.0)


def test_macd_histogram_waits_for_the_signal_line() -> None:
    values = feed(ind.MACD(2, 3, 2, "hist"), [1, 2, 3, 4, 5, 6])
    assert values[:3] == [None, None, None]
    assert values[3] is not None


def test_every_catalogued_indicator_builds_and_runs() -> None:
    for definition in ind.DEFINITIONS:
        params = {p.name: p.default for p in definition.params}
        series = definition.make(params)
        values = [series.update(bar(100 + i, high=101 + i, low=99 + i)) for i in range(300)]
        assert values[-1] is not None, definition.name


# --- the spec ------------------------------------------------------------------


def rule(left: dict[str, Any], op: str, right: dict[str, Any]) -> dict[str, Any]:
    return {"left": left, "op": op, "right": right}


def i(name: str, **params: float) -> dict[str, Any]:
    return {"kind": "indicator", "name": name, "params": params}


def v(value: float) -> dict[str, Any]:
    return {"kind": "value", "value": value}


def spec(**changes: Any) -> BuilderSpec:
    raw: dict[str, Any] = {
        "name": "Test",
        "universe": {"universe": "all"},
        "entry": {"rules": [rule(i("close"), "crosses_above", i("sma", period=3))]},
        "exit": {"rules": [rule(i("close"), "crosses_below", i("sma", period=3))]},
        "sizing": {"max_positions": 2},
    }
    raw.update(changes)
    return BuilderSpec.model_validate(raw)


def test_a_strategy_without_an_entry_rule_is_refused() -> None:
    with pytest.raises(ValidationError, match="never buys"):
        spec(entry={"rules": []})


def test_a_strategy_with_no_way_out_is_refused() -> None:
    with pytest.raises(ValidationError, match="held to the end"):
        spec(exit={"rules": []})


def test_an_unknown_indicator_names_the_real_ones() -> None:
    with pytest.raises(ValidationError, match="Known:"):
        spec(entry={"rules": [rule(i("momentum_9_2"), "above", v(0))]})


def test_a_parameter_out_of_range_is_refused() -> None:
    with pytest.raises(ValidationError, match="between"):
        spec(entry={"rules": [rule(i("sma", period=0), "above", v(0))]})


def test_a_rule_comparing_a_thing_with_itself_is_refused() -> None:
    with pytest.raises(ValidationError, match="compared with itself"):
        spec(entry={"rules": [rule(i("sma", period=5), "above", i("sma", period=5))]})


def test_renaming_does_not_change_what_the_strategy_is() -> None:
    a = spec(name="One")
    b = spec(name="Two", description="different words")
    assert a.digest() == b.digest()
    assert a.id != b.id


def test_the_summary_says_what_it_buys_and_sells_on() -> None:
    text = " ".join(summarise(spec(risk={"stop_loss_pct": 5})))
    assert "Close crosses above SMA(3)" in text
    assert "5% below the entry" in text


def test_every_template_is_valid_and_summarises() -> None:
    assert len(TEMPLATES) >= 4
    for template in TEMPLATES:
        assert summarise(template)


# --- the compiled strategy -----------------------------------------------------


def series(prices: Sequence[float], symbol: str = "AAA") -> list[PanelRow]:
    return [
        PanelRow(
            day=START + timedelta(days=d),
            symbol=symbol,
            close=p,
            volume=1000.0,
            turnover=1e9,
            isin=f"T{symbol}",
        )
        for d, p in enumerate(prices)
    ]


def holding_after(strategy: BuiltStrategy, prices: Sequence[float]) -> bool:
    rows = series(prices)
    return bool(strategy.target_weights(MarketView(as_of=rows[-1].day, history={"AAA": rows})))


UP = [10, 10, 10, 9, 12]  # close crosses above SMA(3) on the last bar


def test_an_entry_rule_opens_a_position() -> None:
    assert holding_after(BuiltStrategy(spec()), UP)
    assert not holding_after(BuiltStrategy(spec()), UP[:-1])


def test_a_stop_loss_closes_on_the_close_below_it() -> None:
    s = spec(exit={"rules": []}, risk={"stop_loss_pct": 10})
    assert holding_after(BuiltStrategy(s), [*UP, 11])  # -8.3%: still held
    assert not holding_after(BuiltStrategy(s), [*UP, 10.7])  # -10.8%: stopped


def test_a_take_profit_closes_above_the_target() -> None:
    s = spec(exit={"rules": []}, risk={"take_profit_pct": 20})
    assert not holding_after(BuiltStrategy(s), [*UP, 14.5])


def test_a_trailing_stop_follows_the_highest_close() -> None:
    s = spec(exit={"rules": []}, risk={"trailing_stop_pct": 10})
    assert holding_after(BuiltStrategy(s), [*UP, 20, 18.5])
    assert not holding_after(BuiltStrategy(s), [*UP, 20, 17.9])


def test_a_holding_limit_closes_after_n_bars() -> None:
    s = spec(exit={"rules": []}, risk={"max_hold_days": 2})
    assert holding_after(BuiltStrategy(s), [*UP, 13])
    assert not holding_after(BuiltStrategy(s), [*UP, 13, 14])


def test_slots_go_to_the_highest_ranked() -> None:
    s = spec(
        sizing={"max_positions": 1, "ranking": {"by": i("roc", period=1), "order": "highest"}},
    )
    a = series(UP, "AAA")
    b = series([10, 10, 10, 9, 15], "BBB")
    weights = BuiltStrategy(s).target_weights(
        MarketView(as_of=a[-1].day, history={"AAA": a, "BBB": b})
    )
    assert weights == {"BBB": 1.0}


def test_a_cached_replay_gives_the_same_answer_as_a_fresh_one() -> None:
    """The cache is what makes daily decisions linear; it must change nothing."""
    import math

    prices = [100 + 10 * math.sin(d / 3) + d * 0.1 for d in range(120)]
    rows = series(prices)
    s = spec(risk={"trailing_stop_pct": 5})
    incremental = BuiltStrategy(s)
    for end in range(1, len(rows) + 1):
        view = MarketView(as_of=rows[end - 1].day, history={"AAA": rows[:end]})
        cached = incremental.target_weights(view)
        fresh = BuiltStrategy(s).target_weights(view)
        assert cached == fresh, f"diverged on bar {end}"


def test_a_corporate_action_restarts_the_replay() -> None:
    """Back-adjustment changes every earlier close; the old replay is invalid."""
    s = spec()
    strategy = BuiltStrategy(s)
    rows = series(UP)
    strategy.target_weights(MarketView(as_of=rows[-1].day, history={"AAA": rows}))
    halved = [row.adjusted(2.0) for row in rows] + series([*UP, 6.5])[-1:]
    view = MarketView(as_of=halved[-1].day, history={"AAA": halved})
    assert strategy.target_weights(view) == BuiltStrategy(s).target_weights(view)


# --- in the engines ------------------------------------------------------------


def panel(n_symbols: int = 6, n_days: int = 260) -> list[PanelRow]:
    import math

    rows: list[PanelRow] = []
    for s in range(n_symbols):
        for d in range(n_days):
            price = 100 + 15 * math.sin((d + 7 * s) / 9) + 0.05 * d
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"SYM{s}",
                    close=price,
                    volume=1000.0,
                    turnover=1e9,
                    isin=f"BLD{s:06d}",
                )
            )
    return rows


def test_tier_a_and_tier_b_agree_on_a_builder_strategy() -> None:
    rows = panel()
    s = spec(
        entry={"rules": [rule(i("close"), "crosses_above", i("sma", period=10))]},
        exit={"rules": [rule(i("close"), "crosses_below", i("sma", period=10))]},
        sizing={"max_positions": 3},
        risk={"stop_loss_pct": 6},
    )
    a = vector.run(rows, BuiltStrategy(s), warmup=20, rebalance_every=1, asset_class="equity")
    b = event_driven.run(rows, BuiltStrategy(s), warmup=20, rebalance_every=1, asset_class="equity")
    assert a.fills
    reconciled = event_driven.reconcile(a.equity, b.equity)
    assert reconciled.agrees, f"diverged by {reconciled.max_relative:.2e}"


def test_holding_unchanged_trades_only_on_entries_and_exits() -> None:
    rows = panel()
    s = spec(
        entry={"rules": [rule(i("close"), "crosses_above", i("sma", period=10))]},
        exit={"rules": [rule(i("close"), "crosses_below", i("sma", period=10))]},
        sizing={"max_positions": 3},
    )
    steady = BuiltStrategy(s)
    drifting = BuiltStrategy(s)
    drifting.hold_unchanged = False
    held = vector.run(rows, steady, warmup=20, rebalance_every=1, asset_class="equity")
    rebalanced = vector.run(rows, drifting, warmup=20, rebalance_every=1, asset_class="equity")
    assert 0 < len(held.fills) < len(rebalanced.fills)


def test_adjusting_a_row_divides_every_price() -> None:
    row = PanelRow(
        day=START, symbol="X", close=100, volume=1, turnover=1, open=90, high=110, low=80
    )
    adjusted = row.adjusted(2.0)
    assert (adjusted.open, adjusted.high, adjusted.low, adjusted.close) == (45, 55, 40, 50)
    unrecorded = PanelRow(day=START, symbol="X", close=100, volume=1, turnover=1)
    assert unrecorded.adjusted(2.0).high == 0.0


# --- storage and the endpoints -------------------------------------------------


@pytest.fixture()
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ws.Workspace:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    return ws.Workspace(id="tenant-a").ensure()


def test_a_saved_strategy_loads_back_unchanged(space: ws.Workspace) -> None:
    s = spec()
    store.save(space, s)
    assert store.load(space, s.id) == s
    assert [x.id for x in store.all_specs(space)] == [s.id]
    assert store.delete(space, s.id)
    assert store.load(space, s.id) is None


def test_a_non_builder_id_is_never_a_path(space: ws.Workspace) -> None:
    assert store.load(space, "../../etc/passwd") is None
    with pytest.raises(ValueError, match="not a builder"):
        store.delete(space, "momentum_12_1")


def test_validate_returns_sentences_not_a_stack_trace() -> None:
    bad = builder_routes.validate(builder_routes.SpecRequest(spec={"name": "x", "entry": {}}))
    assert bad["ok"] is False
    assert any("never buys" in e for e in bad["errors"])
    good = builder_routes.validate(builder_routes.SpecRequest(spec=spec().model_dump()))
    assert good["ok"] is True
    assert good["summary"]


def test_the_catalog_is_the_code(space: ws.Workspace) -> None:
    catalog = builder_routes.catalog()
    assert {d["name"] for d in catalog["indicators"]} == set(ind.BY_NAME)
    assert len(catalog["templates"]) == len(TEMPLATES)
