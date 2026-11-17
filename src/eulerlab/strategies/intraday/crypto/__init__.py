"""Minute-level crypto intraday signals, priced against Delta Exchange India.

### Provenance is a field, not a footnote

Ten signals, and they do **not** all have the same standing. One is from a
peer-reviewed paper whose rules were read in full; several are families the
academic literature documents; the rest are practitioner constructions that are
widely used and, as far as this search found, never validated in a journal.

Conflating those would be the more comfortable presentation and the less useful
one, so `provenance` is a field on every signal and the interface shows it. A
practitioner rule is not worthless — it is untested, which is a different thing
and is exactly what this platform exists to measure.

### The cost is the point

Crypto has run gross of costs here since it landed (S-028). These are priced
against Delta Exchange India's published schedule: 0.05% taker, 0.02% maker,
plus 18% GST on the fee, so a taker round trip is **0.118% of notional**.

That number decides most of what follows. A minute-level signal has to clear
0.118% per round trip before it has earned anything, and Mesfin's MNQ study
found no intraday family whose gross edge cleared a comparable friction. The
prior for everything here is therefore negative, and a positive result is a
claim against evidence rather than in a vacuum.

### Sessions, for a market that has none

Crypto trades continuously, so "the session" is a convention rather than a
fact. Midnight UTC is used throughout because that is where the daily bar
already breaks in `alt_panel`, and two definitions of a day inside one
repository is how a backtest ends up disagreeing with itself.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.crypto.common import CryptoSignal, Detect, _vwap
from eulerlab.strategies.intraday.crypto.funding_drift import SIGNALS as _funding_drift
from eulerlab.strategies.intraday.crypto.funding_drift import funding_drift
from eulerlab.strategies.intraday.crypto.par_deviation import SIGNALS as _par_deviation
from eulerlab.strategies.intraday.crypto.par_deviation import _poly_fit_next, par_deviation
from eulerlab.strategies.intraday.crypto.range_compression import SIGNALS as _range_compression
from eulerlab.strategies.intraday.crypto.range_compression import range_compression
from eulerlab.strategies.intraday.crypto.session_momentum import SIGNALS as _session_momentum
from eulerlab.strategies.intraday.crypto.session_momentum import session_momentum
from eulerlab.strategies.intraday.crypto.session_reversal import SIGNALS as _session_reversal
from eulerlab.strategies.intraday.crypto.session_reversal import session_reversal
from eulerlab.strategies.intraday.crypto.trend_pullback import SIGNALS as _trend_pullback
from eulerlab.strategies.intraday.crypto.trend_pullback import trend_pullback
from eulerlab.strategies.intraday.crypto.utc_open_range import SIGNALS as _utc_open_range
from eulerlab.strategies.intraday.crypto.utc_open_range import utc_open_range
from eulerlab.strategies.intraday.crypto.volume_climax import SIGNALS as _volume_climax
from eulerlab.strategies.intraday.crypto.volume_climax import volume_climax
from eulerlab.strategies.intraday.crypto.vwap_breakout import SIGNALS as _vwap_breakout
from eulerlab.strategies.intraday.crypto.vwap_breakout import vwap_breakout
from eulerlab.strategies.intraday.crypto.vwap_reversion import SIGNALS as _vwap_reversion
from eulerlab.strategies.intraday.crypto.vwap_reversion import vwap_reversion

CRYPTO_SIGNALS: dict[str, CryptoSignal] = {
    signal.id: signal
    for signal in (
        *_par_deviation,
        *_session_momentum,
        *_session_reversal,
        *_vwap_reversion,
        *_vwap_breakout,
        *_utc_open_range,
        *_volume_climax,
        *_range_compression,
        *_trend_pullback,
        *_funding_drift,
    )
}


__all__ = [
    "CRYPTO_SIGNALS",
    "CryptoSignal",
    "Detect",
    "_poly_fit_next",
    "_vwap",
    "funding_drift",
    "par_deviation",
    "range_compression",
    "session_momentum",
    "session_reversal",
    "trend_pullback",
    "utc_open_range",
    "volume_climax",
    "vwap_breakout",
    "vwap_reversion",
]
