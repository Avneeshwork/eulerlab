"""The bracket engine never carries a position past the session it opened in.

This invariant is load-bearing twice over, and silent both times if it breaks.

`bracket._cost` bills NSE fills at `EQUITY_INTRADAY` rates on the strength of
it — delivery rates are several times higher, so a position that survived the
close would be costed as though it had not. And the US panel stores raw
exchange prices with no split or dividend adjustment (`corp_actions.alpaca_feed`
exists but is wired to nothing); that is harmless only because a position that
never survives a close never spans a corporate action.

Neither claim was tested. Both were comments.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from eulerlab.intraday import bracket
from eulerlab.intraday.tweezer import IST, Candle, Plan, Rules

SESSION_OPEN = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
RULES = Rules()


def _session(
    seed: int, minutes: int, start: datetime, *, drift: float = 0.6, base: float = 100.0
) -> list[Candle]:
    """A random walk, so the exit path is not the one the author had in mind.

    `drift` small enough keeps the walk inside the bracket, which is the only
    way to reach the forced close — see `_quiet`.
    """
    rng = random.Random(seed)
    price = base
    bars: list[Candle] = []
    for i in range(minutes):
        step = rng.uniform(-drift, drift)
        open_ = price
        close = max(1.0, price + step)
        high = max(open_, close) + rng.uniform(0, drift * 0.66)
        low = min(open_, close) - rng.uniform(0, drift * 0.66)
        bars.append(
            Candle(
                ts=start + timedelta(minutes=i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
            )
        )
        price = close
    return bars


def _quiet(seed: int, minutes: int, start: datetime) -> list[Candle]:
    """A session that fills the entry and then goes nowhere.

    Mean-reverting inside a 0.5 band around the trigger, so the stop at -1.0R
    and the target at +1.5R are both out of reach for the whole session. Built
    deliberately: a plain random walk always resolves through a stop or a
    target, which leaves the forced close untested and every assertion here
    vacuous. That is not hypothetical — the first version of this file passed
    with the forced close deleted.
    """
    rng = random.Random(seed)
    price = 100.05
    bars: list[Candle] = []
    for i in range(minutes):
        # Pulled back toward the centre each step, so the band holds over 375
        # bars rather than only over the few an unbounded walk stays inside.
        price += (100.05 - price) * 0.4 + rng.uniform(-0.08, 0.08)
        open_, close = price, price + rng.uniform(-0.04, 0.04)
        bars.append(
            Candle(
                ts=start + timedelta(minutes=i),
                open=open_,
                high=max(open_, close) + 0.02,
                low=min(open_, close) - 0.02,
                close=close,
                volume=1000.0,
            )
        )
        price = close
    return bars


def _plan(entry: float) -> Plan:
    risk = 1.0
    return Plan(
        signal_ts=SESSION_OPEN,
        entry=entry,
        stop=entry - risk,
        target_1=entry + 1.5 * risk,
        target_2=entry + 3.0 * risk,
        r=risk,
        shares_1=60,
        shares_2=40,
        risk_pct=1.0,
    )


def test_a_filled_trade_always_exits_in_full() -> None:
    """Whatever the path, nothing is still held when the engine returns."""
    for maker in (_session, _quiet):
        filled_seen = 0
        for seed in range(100):
            bars = maker(seed, 375, SESSION_OPEN)
            trade = bracket.run(_plan(100.0), bars, RULES, asset_class="equity")
            if not trade.filled:
                continue
            filled_seen += 1
            assert trade.shares_exited == trade.plan.shares, (
                f"{maker.__name__} seed {seed}: "
                f"{trade.plan.shares - trade.shares_exited} shares still held"
            )
        # A fixture where nothing fills passes while asserting nothing.
        assert filled_seen > 20, (
            f"{maker.__name__}: only {filled_seen} of 100 paths filled; the fixture stopped testing"
        )


def test_no_exit_lands_after_the_session_end() -> None:
    """The forced close fires at `session_end_index`, not at the end of the data.

    The distinction matters because callers pass a window that deliberately runs
    past the close — the bars after it exist so a stop can be checked against
    real prices, not so a position can be held into them.
    """
    closed_at_session_end = 0
    for seed in range(100):
        # 375 in-session minutes, then a second day's worth of bars appended.
        # The quiet fixture is the load-bearing one: it reaches the close still
        # holding, so the forced exit is what has to fire.
        session = _quiet(seed, 375, SESSION_OPEN)
        overnight_start = SESSION_OPEN + timedelta(days=1)
        forward = session + _session(seed + 10_000, 375, overnight_start)
        trade = bracket.run(
            _plan(100.0),
            forward,
            RULES,
            session_end_index=len(session) - 1,
            asset_class="equity",
        )
        assert trade.filled, f"seed {seed}: the quiet fixture stopped filling"
        if any(e.reason == "session end" for e in trade.exits):
            closed_at_session_end += 1
        last = session[-1].ts
        for exit_ in trade.exits:
            assert exit_.ts <= last, f"seed {seed}: exited at {exit_.ts}, after the {last} close"
            assert trade.entry_ts is not None
            assert exit_.ts.date() == trade.entry_ts.date(), (
                f"seed {seed}: entered {trade.entry_ts} and exited {exit_.ts} — held overnight"
            )
    # Without this the assertions above hold vacuously for any fixture that
    # happens to resolve early, which is how the first version of this test
    # passed with the forced close deleted.
    assert closed_at_session_end > 90, (
        f"only {closed_at_session_end} of 100 runs reached the forced close; "
        "the fixture is no longer exercising it"
    )
