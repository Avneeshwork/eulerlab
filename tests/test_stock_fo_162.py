"""Research 162: beta, MAX, illiquidity, pinning and OI build-up (H-0083 to H-0087)."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, timedelta

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import minute_six as six
from eulerlab.strategies.studies import stock_fo as fo

N = 375
START = date(2023, 1, 2)


def _snap(close: float, when: date, *, late: float | None = None) -> six.Snap:
    closes = [close] * N
    if late is not None:
        closes = [close] * fo.PIN_MINUTE + [late] * (N - fo.PIN_MINUTE)
    prices = tuple(closes)
    found = six.snap(ip.Day(when, prices, prices, prices, prices, tuple([100.0] * N), N - 1))
    assert found is not None
    return found


def _days(n: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def test_a_split_sized_move_is_not_a_daily_return() -> None:
    days = _days(3)
    snaps = {
        days[0]: _snap(100.0, days[0]),
        days[1]: _snap(50.0, days[1]),
        days[2]: _snap(51.0, days[2]),
    }
    assert fo.daily_returns(snaps) == {days[2]: 51.0 / 50.0 - 1.0}


def test_beta_and_max_use_only_earlier_sessions() -> None:
    days = _days(fo.BETA_DAYS + 1)
    market = {d: (0.01 if i % 2 else -0.01) for i, d in enumerate(days)}
    price, high, low = 100.0, {}, {}
    for i, d in enumerate(days):
        if i:
            price *= 1 + 2 * market[d]
        high[d] = _snap(price, d)
        low[d] = _snap(100.0 + 0.001 * i, d)
    betas, maxes = fo.beta_and_max({"HIGH": high, "LOW": low}, market)
    last = {symbol: beta for beta, symbol, _ in betas[days[-1]]}
    assert abs(last["HIGH"] - 2.0) < 0.05 and abs(last["LOW"]) < 0.05
    assert days[fo.BETA_MIN] not in betas and days[fo.BETA_MIN + 1] in betas
    assert maxes[days[-1]]


def test_illiquid_ranks_fill_at_1441() -> None:
    days = _days(fo.VALUE_DAYS + 1)
    ranks = fo.illiquid_ranks({"A": {d: _snap(100.0, d) for d in days}})
    ((value, symbol, fill),) = ranks[days[-1]]
    assert symbol == "A" and fill.entry_minute == fo.LATE_MINUTE + 1 and value > 0


def _fo(day: date, oi: dict[str, float], pin: dict[str, list[object]]) -> fo.FoDay:
    return {"d": day.isoformat(), "oi": oi, "pin": pin}


def test_pinning_trades_toward_the_strike_between_one_and_three_percent() -> None:
    before, expiry = date(2023, 3, 28), date(2023, 3, 29)
    snaps = {
        "A": {expiry: _snap(100.0, expiry, late=98.0)},  # strike 100: 2% above, buy
        "B": {expiry: _snap(100.0, expiry, late=99.7)},  # 0.3% away: no trade
    }
    data = {
        before: _fo(
            before,
            {},
            {"A": [expiry.isoformat(), 100.0, 1e6], "B": [expiry.isoformat(), 100.0, 1e6]},
        ),
        expiry: _fo(expiry, {}, {}),
    }
    trades = fo.pin_trades(snaps, data)
    assert [(s, f.direction, f.entry_minute) for _, s, f in trades] == [("A", 1, fo.PIN_MINUTE + 1)]


def test_build_up_follows_price_when_open_interest_rises() -> None:
    d0, d1, d2 = _days(3)
    snaps = {
        "UP": {d0: _snap(100.0, d0), d1: _snap(103.0, d1), d2: _snap(103.0, d2)},
        "DOWN": {d0: _snap(100.0, d0), d1: _snap(97.0, d1), d2: _snap(97.0, d2)},
        "FLAT_OI": {d0: _snap(100.0, d0), d1: _snap(103.0, d1), d2: _snap(103.0, d2)},
    }
    data = {
        d0: _fo(d0, {"UP": 100.0, "DOWN": 100.0, "FLAT_OI": 100.0}, {}),
        d1: _fo(d1, {"UP": 115.0, "DOWN": 120.0, "FLAT_OI": 101.0}, {}),
        d2: _fo(d2, {}, {}),
    }
    trades = {s: f.direction for _, s, f in fo.build_up_trades(snaps, data)}
    assert trades == {"DOWN": -1, "UP": 1}


def test_bhavcopy_reduction_sums_futures_and_finds_the_largest_strike() -> None:
    header = [
        "INSTRUMENT",
        "SYMBOL",
        "EXPIRY_DT",
        "STRIKE_PR",
        "OPTION_TYP",
        "CLOSE",
        "SETTLE_PR",
        "CONTRACTS",
        "OPEN_INT",
    ]
    rows = [
        ["FUTSTK", "ABC", "30-Mar-2023", "0", "XX", "100", "100", "10", "500"],
        ["FUTSTK", "ABC", "27-Apr-2023", "0", "XX", "101", "101", "10", "300"],
        ["OPTSTK", "ABC", "30-Mar-2023", "100", "CE", "2", "2", "10", "700"],
        ["OPTSTK", "ABC", "30-Mar-2023", "100", "PE", "2", "2", "10", "400"],
        ["OPTSTK", "ABC", "30-Mar-2023", "110", "CE", "1", "1", "10", "900"],
        ["OPTSTK", "ABC", "27-Apr-2023", "120", "CE", "1", "1", "10", "9000"],
    ]
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(header)
    writer.writerows(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fo.csv", text.getvalue())
    reduced = fo.reduce_bhavcopy(buffer.getvalue(), "2023-03-28")
    assert reduced["oi"] == {"ABC": 800.0}
    assert reduced["pin"]["ABC"] == ["2023-03-30", 100.0, 1100.0]
