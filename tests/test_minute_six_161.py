"""Research 161: six minute-level cash rules (H-0077 to H-0082)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.corp_actions.parse import CorporateAction, Kind, ParsedComponent
from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import minute_six as six

N = 375
DAY = date(2023, 5, 4)


def _day(closes: list[float], when: date = DAY) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    prices = tuple(closes)
    return ip.Day(when, prices, prices, prices, prices, tuple([100.0] * N), N - 1)


def _snap(closes: list[float], when: date = DAY) -> six.Snap:
    found = six.snap(_day(closes, when))
    assert found is not None
    return found


def test_a_snap_keeps_five_minute_closes_and_next_minute_fills() -> None:
    s = _snap([100.0] * 120 + [105.0] * 255)
    assert s.closes[six._k(120)] == 105.0 and s.closes[six._k(115)] == 100.0
    assert s.fill_minutes[six._k(115)] == 116 and s.entry_minute == six.DAY_START


def test_industry_laggards_score_against_peers_without_the_stock() -> None:
    up = [100.0] * 60 + [102.0] * 315
    flat = [100.0] * N
    snaps = {
        "A": {DAY: _snap(up)},
        "B": {DAY: _snap(up)},
        "C": {DAY: _snap(up)},
        "D": {DAY: _snap(flat)},
    }
    ranks = six.industry_ranks(snaps, dict.fromkeys("ABCD", "Banks"))
    scores = {symbol: score for score, symbol, _ in ranks[DAY]}
    assert scores["D"] > 0.019 and scores["A"] < 0
    assert all(fill.entry_minute == six.INDUSTRY_MINUTE + 1 for _, _, fill in ranks[DAY])


def test_a_small_industry_is_not_ranked() -> None:
    snaps = {s: {DAY: _snap([100.0] * N)} for s in "ABC"}
    assert not six.industry_ranks(snaps, dict.fromkeys("ABC", "Banks"))


def test_market_laggards_trade_the_thin_stocks_that_moved_least() -> None:
    days = [DAY + timedelta(days=i) for i in range(six.VALUE_DAYS + 1)]
    today = days[-1]
    snaps: dict[str, dict[date, six.Snap]] = {}
    for n, symbol in enumerate(["THIN1", "THIN2", "THICK1", "THICK2"]):
        rise = 101.0 if symbol == "THIN2" else 100.0
        snaps[symbol] = {d: _snap([100.0 * (1 + n)] * 70 + [rise * (1 + n)] * 305, d) for d in days}
    trades = six.market_laggards(snaps, {today: 0.006})
    picked = [symbol for d, symbol, _ in trades if d == today]
    assert picked == ["THIN1", "THIN2"] and all(f.direction == 1 for _, _, f in trades)


def test_a_pair_opens_at_two_sigma_and_closes_when_the_spread_crosses_zero() -> None:
    a = _snap([100.0] * 30 + [103.0] * 60 + [99.0] * 285)
    b = _snap([100.0] * N)
    legs = six.pair_trade(a, b, 0.01)
    assert legs is not None
    short, long = legs
    assert short.direction == -1 and long.direction == 1
    assert short.entry_minute == 31 and short.reason == "zero" and short.exit_minute == 91


def test_pairs_are_formed_within_an_industry_only() -> None:
    days = [DAY + timedelta(days=i) for i in range(4)]
    snaps = {
        s: {
            d: _snap([100.0 + i] * N if s != "C" else [100.0 + 3 * i] * N, d)
            for i, d in enumerate(days)
        }
        for s in "ABC"
    }
    snaps["A"] = {
        d: _snap([100.0] * 300 + [100.0 + i * (1 if i % 2 else -1)] * 75, d)
        for i, d in enumerate(days)
    }
    pairs = six.form_pairs(snaps, {"A": "x", "B": "y", "C": "x"}, days)
    assert [(a, b) for a, b, _ in pairs] == [("A", "C")]


def test_ex_dates_pick_splits_and_large_dividends() -> None:
    actions = [
        CorporateAction("I1", "S", DAY, (ParsedComponent(Kind.SPLIT, "split"),), "split"),
        CorporateAction(
            "I2", "D", DAY, (ParsedComponent(Kind.DIVIDEND, "div", dividend_amount=2.0),), "div"
        ),
        CorporateAction(
            "I3", "E", DAY, (ParsedComponent(Kind.DIVIDEND, "div", dividend_amount=0.5),), "div"
        ),
    ]
    events = six.ex_dates(actions)
    before = DAY - timedelta(days=1)
    snaps = {s: {before: _snap([100.0] * N, before), DAY: _snap([99.0] * N)} for s in "SDE"}
    assert [s for _, s, _ in six.ex_date_trades(snaps, events, "split")] == ["S"]
    assert [s for _, s, _ in six.ex_date_trades(snaps, events, "dividend")] == ["D"]


def test_a_vwap_stretch_is_faded_and_exits_at_the_cross() -> None:
    closes = [100.0] * 60 + [97.0] * 20 + [101.0] * 295
    fill = six.vwap_trade(_day(closes))
    assert fill is not None and fill.direction == 1
    assert fill.minute == 60 and fill.entry_minute == 61 and fill.reason == "vwap"


def test_no_stretch_before_ten() -> None:
    closes = [100.0] * 20 + [97.0] * 20 + [100.0] * 335
    assert six.vwap_trade(_day(closes)) is None
