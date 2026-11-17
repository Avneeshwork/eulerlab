"""Signals coded from published intraday papers.

The tests that matter here are not "does it fire" but "does it fire the way the
paper says, and can the harness fool itself". A signal library whose prior is
failure is only useful if a positive result can be trusted to mean something,
and that depends entirely on the scanner not manufacturing trades.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers import SIGNALS, PaperRules


def _candles(
    prices: list[tuple[float, float, float, float]],
    *,
    volume: float = 1000.0,
    start: datetime | None = None,
    step_minutes: int = 1,
) -> list[Candle]:
    base = start or datetime(2026, 1, 5, 9, 15, tzinfo=UTC)
    return [
        Candle(
            ts=base + timedelta(minutes=step_minutes * i),
            open=o,
            high=h,
            low=low,
            close=c,
            volume=volume,
        )
        for i, (o, h, low, c) in enumerate(prices)
    ]


def _flat(n: int, price: float = 100.0) -> list[tuple[float, float, float, float]]:
    """Quiet bars. The range is small on purpose: an ATR-derived stop from wide
    bars lands outside the risk band and every test would fail on sizing rather
    than on the thing it is checking."""
    return [(price, price + 0.1, price - 0.1, price)] * n


# --- every signal is well-behaved ------------------------------------------


@pytest.mark.parametrize("signal_id", sorted(SIGNALS))
def test_a_signal_returns_a_reason_rather_than_none(signal_id: str) -> None:
    """ "No trade today" and "no trade because volume was 1.2x" are different
    facts, and only the second says whether the filter is doing anything."""
    outcome = SIGNALS[signal_id].detect(_candles(_flat(5)), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason


@pytest.mark.parametrize("signal_id", sorted(SIGNALS))
def test_a_signal_refuses_a_short_window(signal_id: str) -> None:
    outcome = SIGNALS[signal_id].detect(_candles(_flat(3)), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)


@pytest.mark.parametrize("signal_id", sorted(SIGNALS))
def test_every_signal_carries_its_provenance(signal_id: str) -> None:
    """A signal whose source is a memory is not reproducible, and one whose
    published result is not carried can be read without the prior it argues
    against."""
    signal = SIGNALS[signal_id]
    assert signal.source and ("arXiv" in signal.source or "SSRN" in signal.source)
    assert signal.published


# --- the rules themselves ---------------------------------------------------


def test_opening_range_breakout_needs_a_break_of_the_high() -> None:
    prices = [(100.0, 100.3, 99.9, 100.2)] * 5 + _flat(120, 100.0)
    window = _candles(prices)
    outcome = SIGNALS["orb_breakout"].detect(window, PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason == "no breakout"


def test_opening_range_breakout_fires_above_the_high() -> None:
    prices = [(100.0, 100.3, 99.9, 100.2)] * 5 + _flat(120, 100.0) + [(100.3, 100.5, 100.2, 100.4)]
    outcome = SIGNALS["orb_breakout"].detect(_candles(prices), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Plan)
    assert outcome.entry == 100.4
    assert outcome.stop < outcome.entry


def test_opening_range_breakout_skips_a_range_that_closed_down() -> None:
    """The paper takes the long only when the opening range closes above its
    open; the mirror case is the short, which this engine cannot hold."""
    prices = [(100.3, 100.4, 99.9, 100.0)] * 5 + _flat(120, 100.0) + [(100.3, 100.5, 100.2, 100.4)]
    outcome = SIGNALS["orb_breakout"].detect(_candles(prices), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason == "range closed down"


def test_stocks_in_play_refuses_without_prior_sessions() -> None:
    """The selection step IS the strategy in Zarattini et al. Degrading to a
    plain breakout when the history is missing would silently test a different
    paper."""
    prices = [(100.0, 100.3, 99.9, 100.2)] * 5 + _flat(120, 100.0) + [(100.3, 100.5, 100.2, 100.4)]
    outcome = SIGNALS["orb_in_play"].detect(_candles(prices), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason == "no relative volume"


def test_volume_spike_needs_an_up_bar() -> None:
    window = _candles(_flat(60))
    window = [
        Candle(c.ts, c.open, c.high, c.low, c.close, 1000.0 + (i % 7) * 25.0)
        for i, c in enumerate(window)
    ]
    heavy = Candle(
        ts=window[-1].ts + timedelta(minutes=1),
        open=100.0,
        high=100.5,
        low=98.0,
        close=98.5,
        volume=1_000_000.0,
    )
    outcome = SIGNALS["volume_spike"].detect([*window, heavy], PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason == "spike is downward"


def test_ou_reversion_needs_price_stretched_below_the_mean() -> None:
    rising = [
        (100.0 + i * 0.1, 100.6 + i * 0.1, 99.4 + i * 0.1, 100.0 + i * 0.1) for i in range(80)
    ]
    outcome = SIGNALS["ou_reversion"].detect(_candles(rising), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason == "not stretched"


# --- the plan geometry ------------------------------------------------------


def test_a_plan_never_places_its_stop_above_its_entry() -> None:
    prices = [(100.0, 100.3, 99.9, 100.2)] * 5 + _flat(120, 100.0) + [(100.3, 100.5, 100.2, 100.4)]
    outcome = SIGNALS["orb_breakout"].detect(_candles(prices), PaperRules(), 1_000_000.0)
    assert isinstance(outcome, Plan)
    assert outcome.stop < outcome.entry < outcome.target_1 < outcome.target_2
    assert outcome.r > 0


def test_a_risk_wider_than_the_band_is_refused() -> None:
    """A stop far from entry is a different trade from the one the paper
    describes, so it is refused rather than sized down."""
    prices = [(100.0, 100.3, 99.9, 100.2)] * 5 + _flat(120, 100.0) + [(100.3, 100.5, 100.2, 100.4)]
    tight = PaperRules(max_risk_pct=0.001)
    outcome = SIGNALS["orb_breakout"].detect(_candles(prices), tight, 1_000_000.0)
    assert isinstance(outcome, Rejected)
    assert outcome.reason == "risk too wide"
