from __future__ import annotations

from datetime import date

from eulerlab.intraday.india_papers import Day
from eulerlab.strategies.studies.fii_participant_oi import (
    backtest,
    parse_report,
    volatility_moderation,
)


def test_parse_report_reads_fii_and_dii_index_futures_net_positions() -> None:
    payload = b"""Title line\nClient Type,Future Index Long,Future Index Short,Future Stock Long\nFII,100,40,5\nDII,30,50,1\nTOTAL,130,90,6\n"""
    assert parse_report(payload) == {"FII": 60, "DII": -20}


def _day(when: date, exit_price: float) -> Day:
    opens: list[float | None] = [100.0] * 360
    opens[355] = exit_price
    highs: list[float | None] = [max(100.0, exit_price)] * 360
    lows: list[float | None] = [min(100.0, exit_price)] * 360
    closes = [100.0] * 360
    closes[355] = exit_price
    return Day(when, tuple(opens), tuple(highs), tuple(lows), tuple(closes), (100.0,) * 360, 359)


def test_fii_position_change_is_delayed_two_full_sessions() -> None:
    sessions = [
        date(2023, 12, 27),
        date(2023, 12, 28),
        date(2023, 12, 29),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    prices = {"RELIANCE": [_day(day, 101.0 if day == sessions[-1] else 100.0) for day in sessions]}
    positions = {
        sessions[0]: {"FII": 10, "DII": 0},
        sessions[1]: {"FII": 20, "DII": 0},
        sessions[2]: {"FII": 30, "DII": 0},
        sessions[3]: {"FII": 40, "DII": 0},
        sessions[4]: {"FII": 50, "DII": 0},
    }

    result = backtest(prices, positions)

    assert [row["day"] for row in result["signals"]] == ["2024-01-02", "2024-01-03"]
    assert result["signals"][-1]["source_report"] == "2023-12-29"
    assert result["signals"][-1]["fii_net_index_futures_change"] == 10
    assert result["trade_log"][-1]["side"] == "long"
    assert result["trade_log"][-1]["gross_pnl"] > 0


def test_volatility_moderation_uses_lagged_fii_shock_and_dii_positioning() -> None:
    sessions = [date.fromordinal(date(2023, 11, 1).toordinal() + i) for i in range(70)]
    closes = tuple(100.0 + (0.1 if i % 2 else 0.0) for i in range(360))
    days = [
        Day(when, (100.0,) * 360, (101.0,) * 360, (99.0,) * 360, closes, (100.0,) * 360, 359)
        for when in sessions
    ]
    fii = 0
    positions = {}
    for i, when in enumerate(sessions):
        fii += -100 if i == 60 else 1
        positions[when] = {"FII": fii, "DII": i + 1}

    result = volatility_moderation({"RELIANCE": days}, positions)

    event = next(
        row for row in result["event_log"] if row["source_report"] == sessions[60].isoformat()
    )
    assert event["day"] == sessions[62].isoformat()
    assert event["dii_absorbs_proxy"] is True
    assert result["dii_absorption"]["sessions"] == 1
