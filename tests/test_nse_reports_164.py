"""Research 164: cash rules from NSE bulk deals, SAST, ban list and SLBM (H-0093 to H-0097)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import minute_six_screen as six
from eulerlab.intraday import nse_reports_screen as rep

N = 375
SESSIONS = [date(2023, 3, 20), date(2023, 3, 21), date(2023, 3, 22), date(2023, 3, 24)]

BULK = (
    '"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ","Quantity Traded ",'
    '"Trade Price / Wght. Avg. Price ","Remarks "\n'
    '"21-MAR-2023","AAA","A Ltd","HFT LLP","BUY","1,000","100.00","-"\n'
    '"21-MAR-2023","AAA","A Ltd","HFT LLP","SELL","1,000","100.10","-"\n'
    '"21-MAR-2023","AAA","A Ltd","FUND","BUY","2,000","100.00","-"\n'
    '"21-MAR-2023","BBB","B Ltd","SELLER","SELL","500","50.00","-"\n'
)


def _snap(close: float, when: date) -> six.Snap:
    prices = tuple([close] * N)
    found = six.snap(ip.Day(when, prices, prices, prices, prices, tuple([100.0] * N), N - 1))
    assert found is not None
    return found


def test_bulk_deals_drop_clients_on_both_sides() -> None:
    assert rep.bulk_net(BULK) == {"AAA": 200_000.0, "BBB": -25_000.0}


def test_bulk_deals_trade_the_next_session() -> None:
    buys, sells = rep.bulk_events([(SESSIONS[1], rep.bulk_net(BULK))], SESSIONS)
    assert buys == {"AAA": {SESSIONS[2]: 200_000.0}} and sells == {"BBB": {SESSIONS[2]: 25_000.0}}


def test_a_promoter_disclosure_trades_the_first_session_after_it() -> None:
    evening = datetime(2023, 3, 22, 18, 40, tzinfo=rep.IST)
    morning = datetime(2023, 3, 22, 8, 30, tzinfo=rep.IST)
    midday = datetime(2023, 3, 22, 11, 0, tzinfo=rep.IST)
    assert rep.session_after(SESSIONS, evening) == SESSIONS[3]
    assert rep.session_after(SESSIONS, morning) == SESSIONS[2]
    assert rep.session_after(SESSIONS, midday) == SESSIONS[3]


def test_promoter_buys_keep_only_promoter_acquisitions() -> None:
    text = (
        '{"data": [{"symbol": "A", "promoterType": "Y", "acqSaleType": "Acquisition",'
        ' "timestamp": "21-Mar-2023 18:40", "totAcqShare": "0.25"},'
        ' {"symbol": "B", "promoterType": "N", "acqSaleType": "Acquisition",'
        ' "timestamp": "21-Mar-2023 18:40", "totAcqShare": "2"}]}'
    )
    assert rep.promoter_buys(text) == [("A", datetime(2023, 3, 21, 18, 40, tzinfo=rep.IST), 0.25)]


def test_only_the_first_ban_day_is_an_event() -> None:
    lists = {
        SESSIONS[0]: {"X"},
        SESSIONS[1]: {"X", "Y"},
        SESSIONS[2]: {"Y"},
    }
    assert rep.ban_list("Securities in Ban For Trade Date 21-MAR-2023:\n1,BIOCON\n2,IDEA\n") == {
        "BIOCON",
        "IDEA",
    }
    assert rep.ban_events(lists) == {"Y": {SESSIONS[1]: 1.0}}


def test_heavy_borrowing_is_measured_against_traded_value() -> None:
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(rep.VALUE_DAYS + 2)]
    snaps = {"A": {d: _snap(100.0, d) for d in days}}
    value = snaps["A"][days[0]].value
    heavy = rep.slbm_events([(days[-2], {"A": value * 0.01 / 100.0})], snaps, days)
    light = rep.slbm_events([(days[-2], {"A": value * 0.001 / 100.0})], snaps, days)
    assert list(heavy["A"]) == [days[-1]] and not light


def test_slbm_rows_sum_across_series() -> None:
    text = (
        "ABB INDIA LIMITED ,ABB ,X4,06-APR-2023,N,4,4,4,4,4, ,  120, 480.00,5,4,21-MAR-2023, 1\n"
        "ABB INDIA LIMITED ,ABB ,X5,04-MAY-2023,N,4,4,4,4,4, ,  30, 120.00,5,4,21-MAR-2023, 1\n"
    )
    assert rep.slbm_quantity(text) == {"ABB": 150.0}


def test_trades_take_at_most_ten_a_day_highest_score_first() -> None:
    day = SESSIONS[2]
    snaps = {f"S{i:02d}": {day: _snap(100.0, day)} for i in range(12)}
    events = {f"S{i:02d}": {day: float(i)} for i in range(12)}
    found = rep.trades(snaps, events, -1)
    assert len(found) == 10 and {s for _, s, _ in found} == {f"S{i:02d}" for i in range(2, 12)}
    assert all(f.direction == -1 for _, _, f in found)


def test_daily_ban_trades_short_open_to_close() -> None:
    day = SESSIONS[1]
    bans = {"A": {day: 1.0}, "B": {day: 1.0}}
    bars = {"A": {day: (200.0, 190.0)}, "B": {day: (5.0, 4.0)}}
    (trade,) = rep.daily_ban_trades(bans, bars)
    assert trade.symbol == "A" and trade.direction == -1 and trade.gross > 0
