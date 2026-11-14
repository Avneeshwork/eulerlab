"""The fill-price model (#119, ADR-194): reference, half spread and impact, always against the trade."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from eulerlab.intraday import fill_price
from eulerlab.intraday import rule_engine as engine
from eulerlab.intraday.tweezer import IST, Candle
from test_research_autopilot import GAP_FADE, _gappy


def _model(data: engine.Data, **kw: Any) -> fill_price.PriceModel:
    return fill_price.PriceModel(data, spreads=kw.pop("spreads", {}), **kw)


def test_a_buy_pays_more_and_a_sell_gets_less_than_the_print() -> None:
    data = _gappy()
    model = _model(data)
    day = data.sessions[30]
    bar = data.panel["AAA"][day]
    assert model("AAA", day, 1, "open", 1e5) > bar.open
    assert model("AAA", day, -1, "close", 1e5) < bar.close


def test_impact_grows_with_the_square_root_of_size() -> None:
    small = fill_price.impact_bps(1e5, 1e9, 0.02)
    big = fill_price.impact_bps(4e5, 1e9, 0.02)
    assert big == pytest.approx(2 * small)
    assert fill_price.impact_bps(1e5, 0.0, 0.02) == 100.0  # no traded value, no estimate


def test_thinner_stocks_have_wider_spreads_and_measured_ones_win() -> None:
    assert fill_price.bucket_half_spread(1e10) < fill_price.bucket_half_spread(1e8)
    data = _gappy()
    day = data.sessions[30]
    bucketed = _model(data).extra("AAA", day, 1e5)
    measured = _model(data, spreads={"AAA": 30.0}).extra("AAA", day, 1e5)
    assert measured > bucketed


def test_the_two_bps_already_charged_are_not_charged_twice() -> None:
    """On ₹1,000 crore a day, the model is under 2 bps: nothing extra."""
    data = _gappy()  # every bar trades 1e9 a day
    for bars in data.panel.values():
        for d, bar in list(bars.items()):
            bars[d] = type(bar)(bar.open, bar.close, 1e11)
    assert _model(data).extra("BBB", data.sessions[30], 1e5) == 0.0


def test_a_modelled_screen_earns_less_and_says_how_it_priced() -> None:
    data = _gappy()
    spec = engine.RuleSpec.model_validate(GAP_FADE)
    plain = engine.Engine(data).screen(spec)
    model = _model(data)
    priced = engine.Engine(data, prices=model).screen(spec)
    assert priced["count"] == plain["count"] > 0
    assert priced["per_bps"]["net_mean"] < plain["per_bps"]["net_mean"]
    assert priced["price_model"].startswith("modelled")
    assert "price_model" not in plain
    assert model.fills == 2 * plain["count"]


def test_a_swing_is_priced_at_both_ends() -> None:
    data = _gappy()
    spec = engine.RuleSpec.model_validate({**GAP_FADE, "kind": "swing", "hold": 3, "side": "with"})
    plain = engine.Engine(data).swings(spec)
    priced = engine.Engine(data, prices=_model(data)).swings(spec)
    assert len(plain) == len(priced) > 0
    assert all(p.entry > a.entry and p.exit < a.exit for a, p in zip(plain, priced, strict=True))


def _candles(day: date) -> list[Candle]:
    def at(h: int, m: int, price: float, volume: float) -> Candle:
        ts = datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
        return Candle(ts, price, price, price, price, volume)

    return [at(9, 15, 100.0, 10), at(9, 19, 110.0, 30), at(9, 20, 500.0, 99), at(15, 15, 90.0, 5)]


def test_minute_vwap_reads_only_its_window() -> None:
    day = date(2023, 3, 1)
    assert fill_price.minute_vwap(_candles(day), "open") == pytest.approx(107.5)
    assert fill_price.minute_vwap(_candles(day), "close") == pytest.approx(90.0)
    assert fill_price.minute_vwap([], "open") is None


def test_minute_bars_set_the_reference_when_there_are_some() -> None:
    data = _gappy()
    day = data.sessions[30]
    reference = fill_price.MinuteReference(lambda symbol: _candles(day) if symbol == "AAA" else [])
    model = _model(data, reference=reference)
    assert model("AAA", day, 1, "open", 1e5) > 107.5
    assert model("BBB", day, 1, "open", 1e5) == pytest.approx(
        data.panel["BBB"][day].open * (1 + model.extra("BBB", day, 1e5) / 1e4)
    )
    assert "minute VWAP" in model.describe()


def test_the_reprice_table_lists_each_rule_both_ways() -> None:
    data = _gappy()
    rows = fill_price.compare({"gap fade": engine.RuleSpec.model_validate(GAP_FADE)}, data)
    (row,) = rows
    assert row["net_bps_modelled"] < row["net_bps_official"]
    text = fill_price.markdown(rows, _model(data))
    assert "| gap fade | intraday |" in text and "Mean extra cost" in text


def test_liquidity_uses_only_sessions_before_the_fill() -> None:
    data = _gappy()
    model = _model(data)
    day = data.sessions[30]
    before = model.liquidity("AAA", day)
    bars = data.panel["AAA"]
    for d in data.sessions[30:]:
        bars[d] = type(bars[d])(bars[d].open, bars[d].close * 1.3, 5e9)
    fresh = _model(data)
    assert fresh.liquidity("AAA", day) == before
    assert fresh.liquidity("AAA", day + timedelta(days=60)) != before
