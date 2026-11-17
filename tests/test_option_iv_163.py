"""Research 163: cash rules read from stock options (H-0088 to H-0092)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import minute_six as six
from eulerlab.strategies.studies import option_iv as iv

N = 375
DAY = date(2023, 3, 1)
EXPIRY = date(2023, 3, 30)
YEARS = (EXPIRY - DAY).days / 365.0


def _snap(close: float, when: date) -> six.Snap:
    prices = tuple([close] * N)
    found = six.snap(ip.Day(when, prices, prices, prices, prices, tuple([100.0] * N), N - 1))
    assert found is not None
    return found


def _chain(call_vol: float, put_vol: float, skew_vol: float = 0.30) -> iv.Chain:
    def price(strike: float, vol: float, call: bool) -> float:
        return iv.bs_price(100.0, strike, YEARS, vol, call)

    return {
        "x": EXPIRY.isoformat(),
        "c": [[100.0, price(100.0, 0.30, True)]],
        "p": [[95.0, price(95.0, skew_vol, False)], [100.0, price(100.0, 0.25, False)]],
        "cv": call_vol,
        "pv": put_vol,
    }


def test_implied_vol_inverts_the_price() -> None:
    for call in (True, False):
        price = iv.bs_price(100.0, 105.0, 0.1, 0.4, call)
        found = iv.implied_vol(price, 100.0, 105.0, 0.1, call)
        assert found is not None and abs(found - 0.4) < 1e-6


def test_a_price_below_any_volatility_has_no_iv() -> None:
    assert iv.implied_vol(0.0001, 100.0, 50.0, 0.1, True) is None


def test_day_signals_read_skew_spread_and_put_share() -> None:
    signals = iv.day_signals(_chain(300.0, 100.0, skew_vol=0.45), 100.0, DAY, 0.20)
    assert abs((signals["spread"] or 0) - 0.05) < 1e-4
    assert abs((signals["skew"] or 0) - 0.15) < 1e-4
    assert signals["put_share"] == 0.25
    assert abs((signals["vol_spread"] or 0) - (0.20 - 0.275)) < 1e-4
    assert signals["change"] is None


def test_signals_formed_today_are_traded_on_the_next_session() -> None:
    days = [DAY + timedelta(days=i) for i in range(3)]
    snaps = {"A": {d: _snap(100.0, d) for d in days}}
    options = {d: {"A": _chain(100.0, 100.0)} for d in days}
    ranked = iv.rankings(snaps, options)
    assert set(ranked["spread"]) == {days[1], days[2]}
    assert set(ranked["change"]) == {days[2]}
    ((_, symbol, fill),) = ranked["spread"][days[1]]
    assert symbol == "A" and fill.entry_minute == six.DAY_START
