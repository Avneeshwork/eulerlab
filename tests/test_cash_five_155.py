"""Research 155: five minute-level cash rules (H-0045 to H-0049)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import india_papers as ip

N = 375


def _day(
    closes: list[float],
    *,
    when: date = date(2023, 5, 4),
    highs: dict[int, float] | None = None,
    lows: dict[int, float] | None = None,
    volume: float = 100.0,
    volumes: dict[int, float] | None = None,
) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    high = list(closes)
    low = list(closes)
    for m, h in (highs or {}).items():
        high[m] = h
    for m, x in (lows or {}).items():
        low[m] = x
    vol = [volume] * N
    for m, v in (volumes or {}).items():
        vol[m] = v
    return ip.Day(when, tuple(closes), tuple(high), tuple(low), tuple(closes), tuple(vol), N - 1)


def test_the_breakout_enters_at_the_range_and_leaves_at_the_stop() -> None:
    closes = [100.0, 100.0, 100.5, 101.0, 101.0, 101.0] + [101.0] * 4 + [102.0] * 5 + [99.0] * 10
    day = _day(closes, highs={3: 101.2, 10: 102.0}, lows={15: 98.5})
    fill = five.orb(day, atr=1.0)
    assert fill is not None and fill.direction == 1
    # Minute 10 opened at 102, above the 101.2 range high: the fill is the open.
    assert fill.entry_minute == 10 and fill.entry == pytest.approx(102.0)
    # The stop is 102 - 1.4 = 100.6; minute 15 opened at 99, through it.
    assert fill.reason == "stop" and fill.exit == pytest.approx(99.0)


def test_a_flat_opening_range_is_not_traded() -> None:
    assert five.orb(_day([100.0] * 30), atr=1.0) is None


def test_the_year_high_break_buys_the_next_open_but_not_a_gap_above() -> None:
    day = _day([99.0] * 20 + [101.0] * 10, highs={20: 101.5})
    fill = five.year_high_break(day, level=100.0)
    assert fill is not None and fill.minute == 20 and fill.entry_minute == 21
    assert five.year_high_break(_day([101.0] * 30), level=100.0) is None


def test_extract_finds_in_play_days_against_their_own_history() -> None:
    days = []
    for i in range(16):
        quiet = _day([200.0] * 30, when=date(2023, 4, 3) + timedelta(days=i))
        days.append(quiet)
    busy = _day([200.0] * 30, when=date(2023, 4, 20), volumes=dict.fromkeys(range(1, 6), 500.0))
    days[-1] = busy
    marks = five.extract("X", days)
    assert marks["in_play"][date(2023, 4, 20)].relative_volume == pytest.approx(5.0)


def test_panic_day_buys_the_biggest_fallers_among_the_most_traded() -> None:
    day = date(2023, 5, 4)
    fill = five.Fill(180, 0, 181, 100.0, 355, 101.0)
    marks = {f"S{i:02d}": {day: five.Panic(-0.001 * i, 1e9 - i, fill)} for i in range(60)}
    run = five.evaluate_panic_stocks(marks, {day: -0.015}, [day])
    bought = {t["symbol"] for t in run["trade_log"]}
    # The 50 most traded are S00-S49; the 10 that fell most of those are S40-S49.
    assert bought == {f"S{i:02d}" for i in range(40, 50)}
    assert all(t["side"] == "long" for t in run["trade_log"])


def test_the_premium_trade_sells_a_rich_etf_and_closes_when_it_turns() -> None:
    nifty_prior = _day([20_000.0] * 40, when=date(2023, 5, 3))
    etf_prior = _day([200.0] * 40, when=date(2023, 5, 3))
    nifty = _day([20_000.0] * 40, when=date(2023, 5, 4))
    etf_closes = [200.0] * 20 + [200.5] * 5 + [199.9] * 15  # +25 bps rich from minute 20
    etf = _day(etf_closes, when=date(2023, 5, 4))
    ((day, fill),) = five.premium_trades([nifty_prior, nifty], [etf_prior, etf])
    assert day == date(2023, 5, 4) and fill.direction == -1
    assert fill.entry_minute == 21 and fill.exit_minute == 26


def test_the_variant_filter_keeps_the_strongest_and_drops_late_entries() -> None:
    from eulerlab.intraday import in_play_variants as variants

    day = date(2023, 5, 4)
    early = five.Fill(5, 1, 30, 100.0, 355, 101.0)
    late = five.Fill(5, 1, 200, 100.0, 355, 101.0)
    marks = {
        "A": {day: five.InPlay(5.0, early)},
        "B": {day: five.InPlay(4.0, late)},
        "C": {day: five.InPlay(2.5, early)},
        "D": {day: five.InPlay(1.5, early)},
    }
    kept = variants.trades(marks, top_n=2, min_relative_volume=2.0, latest_entry=60, days={day})
    # A and B are the top two; B entered after 10:15; C and D are not in the top two.
    assert [t.symbol for t in kept] == ["A"]
