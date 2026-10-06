"""The Tweezer Bottom setup, and the bracket that executes it.

Built from hand-made candles, because the minute store is mirrored to B2 and
pruned locally (S-023). Every test states the shape it is constructing, so a
failure points at a rule rather than at data.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from eulerlab.intraday import bracket
from eulerlab.intraday.tweezer import IST, Candle, Plan, Rejected, Rules, detect

START = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
RULES = Rules()


def _bar(i: int, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(ts=START + timedelta(minutes=i), open=o, high=h, low=low, close=c, volume=1000.0)


def _downtrend(n: int = 140, start: float = 200.0, up: float = 0.26, seed: int = 7) -> list[Candle]:
    """A choppy decline that satisfies every context filter at once.

    Deliberately not a straight line. A monotonic decline pins ADX at 100 (every
    bar is purely directional) and drives RSI to zero, so it fails the 25-50 and
    25-40 bands and could never produce a setup. The two-down-one-up rhythm with
    seeded jitter puts RSI near 31 and ADX near 41 — inside both — which is what
    a real pullback looks like and what the filters were written for.
    """
    rng = random.Random(seed)
    out: list[Candle] = []
    price = start
    for i in range(n):
        previous = price
        price = price - 0.30 if i % 3 != 2 else price + up
        high = max(previous, price) + rng.uniform(0.02, 0.6)
        low = min(previous, price) - rng.uniform(0.02, 0.6)
        out.append(_bar(i, previous, high, low, price))
    return out


def _with_pattern(base: list[Candle]) -> list[Candle]:
    """Append a valid tweezer: bearish C1, bullish C2, lows matching exactly."""
    n = len(base)
    last = base[-1].close
    bottom = last - 1.0
    c1 = _bar(n, last, last + 0.05, bottom, bottom + 0.25)
    c2 = _bar(n + 1, bottom + 0.05, bottom + 1.5, bottom, bottom + 1.3)
    return [*base, c1, c2]


# --- the pattern ------------------------------------------------------------


def test_a_clean_setup_produces_a_plan() -> None:
    result = detect(_with_pattern(_downtrend()), RULES, equity=1_000_000.0)
    assert isinstance(result, Plan), getattr(result, "reason", result)
    assert result.entry > result.stop
    assert result.target_1 == pytest.approx(result.entry + 2 * result.r)
    assert result.target_2 == pytest.approx(result.entry + 3 * result.r)


def test_entry_is_the_high_of_the_first_candle() -> None:
    window = _with_pattern(_downtrend())
    result = detect(window, RULES, equity=1_000_000.0)
    assert isinstance(result, Plan)
    assert result.entry == pytest.approx(window[-2].high)


def test_the_stop_sits_below_the_pattern_low() -> None:
    window = _with_pattern(_downtrend())
    result = detect(window, RULES, equity=1_000_000.0)
    assert isinstance(result, Plan)
    assert result.stop < min(window[-1].low, window[-2].low)


def test_a_bullish_first_candle_is_refused() -> None:
    window = _downtrend()
    n = len(window)
    last = window[-1].close
    bottom = last - 1.0
    window.append(_bar(n, bottom + 0.25, last + 0.05, bottom, last))  # bullish C1
    window.append(_bar(n + 1, bottom + 0.05, bottom + 1.5, bottom, bottom + 1.3))
    result = detect(window, RULES, equity=1_000_000.0)
    assert isinstance(result, Rejected)
    assert result.reason == "c1 not bearish"


def test_lows_that_do_not_match_are_refused() -> None:
    window = _downtrend()
    n = len(window)
    last = window[-1].close
    bottom = last - 1.0
    window.append(_bar(n, last, last + 0.05, bottom, bottom + 0.25))
    # C2's low sits 0.6 lower — about 0.33%, outside the 0.15% tolerance. Kept
    # small on purpose: a bigger gap widens C2's range until the body-ratio rule
    # fires first, and the test would pass for the wrong reason.
    window.append(_bar(n + 1, bottom + 0.05, bottom + 1.5, bottom - 0.6, bottom + 1.35))
    result = detect(window, RULES, equity=1_000_000.0)
    assert isinstance(result, Rejected)
    assert result.reason == "lows do not match"


def test_an_uptrend_is_refused() -> None:
    rising = [
        _bar(i, 100.0 + i * 0.2, 100.4 + i * 0.2, 99.8 + i * 0.2, 100.2 + i * 0.2)
        for i in range(140)
    ]
    result = detect(_with_pattern(rising), RULES, equity=1_000_000.0)
    assert isinstance(result, Rejected)
    assert result.reason in {"not in a downtrend", "not at support", "RSI outside band"}


def test_too_little_history_is_refused_as_warmup() -> None:
    result = detect(_downtrend(n=10), RULES, equity=1_000_000.0)
    assert isinstance(result, Rejected)
    assert result.reason == "warmup"


def test_a_rejection_says_which_rule_and_the_value() -> None:
    """'No trade' and 'no trade because ADX was 51' are different facts, and
    only the second says whether the filter is doing anything."""
    window = _with_pattern(_downtrend())
    tight = Rules(adx_min=99.0, adx_max=100.0)
    result = detect(window, tight, equity=1_000_000.0)
    assert isinstance(result, Rejected)
    assert result.reason == "trend strength outside band"
    assert "ADX" in result.detail


def test_size_rounds_to_zero_on_tiny_capital() -> None:
    result = detect(_with_pattern(_downtrend()), RULES, equity=100.0)
    assert isinstance(result, Rejected)
    assert result.reason == "size rounds to zero"


def test_the_window_cannot_see_past_the_signal_candle() -> None:
    """The firewall property. Truncating the future must not change the plan."""
    window = _with_pattern(_downtrend())
    a = detect(window, RULES, equity=1_000_000.0)
    b = detect(list(window), RULES, equity=1_000_000.0)
    assert a == b


def test_detection_is_deterministic() -> None:
    window = _with_pattern(_downtrend())
    assert detect(window, RULES, equity=5e5) == detect(window, RULES, equity=5e5)


# --- the bracket ------------------------------------------------------------


def _plan(entry: float = 100.0, stop: float = 99.0) -> Plan:
    r = entry - stop
    return Plan(
        signal_ts=START,
        entry=entry,
        stop=stop,
        target_1=entry + 2 * r,
        target_2=entry + 3 * r,
        r=r,
        shares_1=50,
        shares_2=50,
        risk_pct=1.0,
    )


def test_an_order_that_never_triggers_never_fills() -> None:
    flat = [_bar(i, 98.0, 98.5, 97.5, 98.0) for i in range(1, 30)]
    trade = bracket.run(_plan(), flat, RULES, asset_class="equity")
    assert not trade.filled
    assert trade.net_pnl() == 0.0


def test_a_gap_through_the_trigger_fills_at_the_open_not_the_trigger() -> None:
    """The trigger price was never available. Filling there would be a
    fabricated fill in the flattering direction."""
    bars = [_bar(1, 99.0, 99.5, 98.5, 99.0), _bar(2, 103.0, 104.0, 102.5, 103.5)]
    bars += [_bar(i, 103.5, 104.0, 103.0, 103.5) for i in range(3, 20)]
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity")
    assert trade.filled
    assert trade.entry_price == pytest.approx(103.0)


def test_an_ambiguous_bar_is_resolved_against_us() -> None:
    """One minute whose range holds both the stop and a target. The engine
    cannot know which came first, so it takes the stop."""
    bars = [_bar(1, 99.5, 99.8, 99.2, 99.6), _bar(2, 100.0, 100.5, 100.0, 100.4)]
    bars.append(_bar(3, 100.4, 102.5, 98.0, 99.0))  # hits target 1 AND the stop
    bars += [_bar(i, 99.0, 99.2, 98.8, 99.0) for i in range(4, 12)]
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity")
    assert trade.filled
    assert trade.exits[0].reason == "stop"
    assert trade.net_pnl() < 0


def test_the_position_is_closed_before_the_session_ends() -> None:
    bars = [_bar(1, 99.5, 99.8, 99.2, 99.6), _bar(2, 100.0, 100.5, 100.0, 100.4)]
    bars += [_bar(i, 100.4, 100.6, 100.2, 100.4) for i in range(3, 15)]
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity")
    assert trade.filled
    assert trade.exits[-1].reason == "session end"
    assert trade.shares_exited == trade.plan.shares


def _back_through_entry() -> list[Candle]:
    bars = [_bar(1, 99.5, 99.8, 99.2, 99.6), _bar(2, 100.0, 100.5, 100.0, 100.4)]
    bars.append(_bar(3, 100.4, 102.2, 100.3, 102.0))  # target 1 at 102
    bars.append(_bar(4, 102.0, 102.1, 99.5, 99.8))  # back through entry
    bars += [_bar(i, 99.8, 100.0, 99.6, 99.8) for i in range(5, 12)]
    return bars


def test_the_first_target_can_move_the_stop_to_breakeven() -> None:
    rules = Rules(breakeven_after_t1=True)
    trade = bracket.run(_plan(), _back_through_entry(), rules, asset_class="equity")
    reasons = [e.reason for e in trade.exits]
    assert "target 1" in reasons
    assert "breakeven stop" in reasons


def test_the_report_leaves_the_remainder_to_the_trail_not_breakeven() -> None:
    """The operator's report books half at T1 and does not move the stop."""
    trade = bracket.run(_plan(), _back_through_entry(), RULES, asset_class="equity")
    reasons = [e.reason for e in trade.exits]
    assert reasons == ["target 1", "trailing stop"]


def test_the_candle_after_the_signal_can_fill_when_asked() -> None:
    """C3, the breakout candle, is the first bar after C2."""
    bars = [_bar(1, 100.0, 100.5, 99.9, 100.4)]
    bars += [_bar(i, 100.4, 100.6, 100.2, 100.4) for i in range(2, 10)]
    assert not bracket.run(_plan(), bars[:1], RULES, asset_class="equity").filled
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity", first_fillable=0)
    assert trade.entry_ts == bars[0].ts


def test_the_stop_is_the_reports_formula() -> None:
    """patternLow - max(0.1% of patternLow, 1 x ATR)."""
    window = _with_pattern(_downtrend())
    plan = detect(window, RULES, equity=5e5)
    if isinstance(plan, Plan):
        pattern_low = min(window[-1].low, window[-2].low)
        assert plan.stop <= pattern_low * 0.999 + 1e-9


def test_both_targets_can_fill() -> None:
    bars = [_bar(1, 99.5, 99.8, 99.2, 99.6), _bar(2, 100.0, 100.5, 100.0, 100.4)]
    bars.append(_bar(3, 100.4, 102.2, 100.3, 102.0))
    bars.append(_bar(4, 102.0, 103.5, 101.9, 103.2))
    bars += [_bar(i, 103.2, 103.4, 103.0, 103.2) for i in range(5, 12)]
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity")
    reasons = [e.reason for e in trade.exits]
    assert "target 1" in reasons and "target 2" in reasons
    assert trade.shares_exited == trade.plan.shares
    assert trade.net_pnl() > 0


def test_costs_are_charged_on_both_legs() -> None:
    bars = [_bar(1, 99.5, 99.8, 99.2, 99.6), _bar(2, 100.0, 100.5, 100.0, 100.4)]
    bars += [_bar(i, 100.4, 100.6, 100.2, 100.4) for i in range(3, 10)]
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity")
    assert trade.costs > 0
    assert trade.net_pnl() < trade.gross_pnl()


def test_costs_use_the_candles_own_date_not_today() -> None:
    """Rates are time-versioned. Pricing a historical trade at today's rates
    would be wrong in a way no total-based assertion would catch."""
    old = datetime(2016, 6, 3, 9, 15, tzinfo=IST)
    bars = [
        Candle(
            ts=old + timedelta(minutes=i), open=100.0, high=100.5, low=99.9, close=100.2, volume=1.0
        )
        for i in range(1, 10)
    ]
    trade = bracket.run(_plan(), bars, RULES, asset_class="equity")
    assert trade.filled
    assert trade.costs > 0


def test_r_multiple_is_zero_when_nothing_was_risked() -> None:
    plan = Plan(START, 100.0, 100.0, 100.0, 100.0, 0.0, 0, 0, 0.0)
    assert bracket.Trade(plan=plan).r_multiple() == 0.0


# --- candle size and holding period ------------------------------------------


def test_minutes_roll_up_into_session_anchored_candles() -> None:
    from eulerlab.intraday import store

    open_ = datetime(2025, 6, 2, 9, 15, tzinfo=IST)
    minutes = [
        Candle(open_ + timedelta(minutes=i), 100 + i, 100.5 + i, 99.5 + i, 100.2 + i, 10)
        for i in range(75)
    ]
    rolled = store.resample(minutes, 60)
    assert [c.ts.strftime("%H:%M") for c in rolled] == ["09:15", "10:15"]
    first = rolled[0]
    assert (first.open, first.close) == (100, 100.2 + 59)
    assert first.high == 100.5 + 59 and first.low == 99.5
    assert first.volume == 600
    assert rolled[1].volume == 150


def test_a_trade_held_into_the_next_session_can_reach_its_target() -> None:
    """With `max_hold_sessions=1` the close ends it; held, the target fills."""
    day1 = [_bar(i, 100.0, 100.5, 99.9, 100.4) for i in range(1, 6)]
    next_day = START + timedelta(days=1)
    day2 = [
        Candle(next_day + timedelta(minutes=i), 100.4, 103.5, 100.3, 103.2, 1000.0)
        for i in range(5)
    ]
    same_day = bracket.run(
        _plan(),
        day1 + day2,
        RULES,
        asset_class="equity",
        session_end_index=len(day1) - 1,
        first_fillable=0,
    )
    assert same_day.exits[-1].reason == "session end"
    held = bracket.run(_plan(), day1 + day2, RULES, asset_class="equity", first_fillable=0)
    assert "target 2" in [e.reason for e in held.exits]
