"""Intraday signals from published papers, coded against this platform.

Every signal here traces to a paper in `docs/RESEARCH/019`, and every one of
them arrives with a **published expectation of failure**. That is not a
disclaimer, it is the point.

### Why a library of failures is worth building

A strategy library normally arrives with a positive prior — someone published a
result, and the noise bar's job is to argue it down. Mesfin (2026) tested
fourteen intraday signal families on 947 days of MNQ futures against five
criteria and **none passed**: maximum gross return across every family was
1.05-1.50 points against a 2.0-point friction cost. So the prior here is already
negative and measured, and a positive result on our data has to argue against
evidence rather than against nothing.

That is the correct posture, and it is one we normally have to manufacture.

### What is faithful here and what is not

**Faithful:** the entry conditions. Each `detect` implements the paper's stated
trigger, on the paper's stated bar geometry, with the thresholds it published.

**Not faithful:** the exits. Mesfin measures a fixed-horizon return (enter at
bar+1, exit at bar+N). This platform's intraday engine is a bracket — stop,
targets, forced close at the session end — because that is what `bracket.run`
simulates and what a real order would be. A bracket exit and a horizon exit are
different strategies over the same signal, and the difference is not small: a
signal with positive drift and fat left tails looks very different under a stop
than under a horizon. Results here therefore **cannot be compared to the
paper's tables directly**, and the note in `docs/RESEARCH/019` says so.

**Also not faithful:** everything is long-only, because `bracket.run` opens with
`Side.BUY` and closes with `Side.SELL`. Short variants are mirrored to the long
side where the mirror is meaningful and omitted where it is not.

**Also different:** the friction. Mesfin's ceiling is 2.0 points round-trip on a
Nasdaq future. Indian equity costs are a percentage, not a point spread, and
include STT and stamp duty. Whether the ceiling transfers is the first thing
running these measures — it is an open question in the note, not an assumption.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.papers.common import (
    ATR_TAIL_PERIODS,
    IST_OPEN,
    Detect,
    PaperRules,
    PaperSignal,
    _atr_now,
    _closes,
    _gap_pct,
    _plan,
    _session_bars,
    _volume_z,
    opening_range_breakout,
)
from eulerlab.strategies.intraday.papers.gap_continuation import SIGNALS as _gap_continuation
from eulerlab.strategies.intraday.papers.gap_continuation import gap_continuation
from eulerlab.strategies.intraday.papers.gap_fill_fade import SIGNALS as _gap_fill_fade
from eulerlab.strategies.intraday.papers.gap_fill_fade import gap_fill_fade
from eulerlab.strategies.intraday.papers.liquidity_grab import SIGNALS as _liquidity_grab
from eulerlab.strategies.intraday.papers.liquidity_grab import liquidity_grab_reversal
from eulerlab.strategies.intraday.papers.orb_breakout import SIGNALS as _orb_breakout
from eulerlab.strategies.intraday.papers.orb_in_play import (
    _RELATIVE_VOLUME_CACHE,
    _RELATIVE_VOLUME_CACHE_MAX,
    orb_stock_in_play,
)
from eulerlab.strategies.intraday.papers.orb_in_play import SIGNALS as _orb_in_play
from eulerlab.strategies.intraday.papers.ou_reversion import SIGNALS as _ou_reversion
from eulerlab.strategies.intraday.papers.ou_reversion import ou_mean_reversion
from eulerlab.strategies.intraday.papers.range_expansion import SIGNALS as _range_expansion
from eulerlab.strategies.intraday.papers.range_expansion import range_expansion
from eulerlab.strategies.intraday.papers.volatility_regime import SIGNALS as _volatility_regime
from eulerlab.strategies.intraday.papers.volatility_regime import volatility_regime_reversal
from eulerlab.strategies.intraday.papers.volume_dryup import SIGNALS as _volume_dryup
from eulerlab.strategies.intraday.papers.volume_dryup import _sma_tail, volume_dryup_reversal
from eulerlab.strategies.intraday.papers.volume_spike import SIGNALS as _volume_spike
from eulerlab.strategies.intraday.papers.volume_spike import volume_spike_momentum

SIGNALS: dict[str, PaperSignal] = {
    signal.id: signal
    for signal in (
        *_orb_breakout,
        *_range_expansion,
        *_liquidity_grab,
        *_gap_fill_fade,
        *_gap_continuation,
        *_volume_spike,
        *_volume_dryup,
        *_volatility_regime,
        *_ou_reversion,
        *_orb_in_play,
    )
}


__all__ = [
    "ATR_TAIL_PERIODS",
    "IST_OPEN",
    "SIGNALS",
    "_RELATIVE_VOLUME_CACHE",
    "_RELATIVE_VOLUME_CACHE_MAX",
    "Detect",
    "PaperRules",
    "PaperSignal",
    "_atr_now",
    "_closes",
    "_gap_pct",
    "_plan",
    "_session_bars",
    "_sma_tail",
    "_volume_z",
    "gap_continuation",
    "gap_fill_fade",
    "liquidity_grab_reversal",
    "opening_range_breakout",
    "orb_stock_in_play",
    "ou_mean_reversion",
    "range_expansion",
    "volatility_regime_reversal",
    "volume_dryup_reversal",
    "volume_spike_momentum",
]
