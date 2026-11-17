"""Shared pieces of the crypto strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers import PaperRules

Detect = Callable[[Sequence[Candle], PaperRules, float], "Plan | Rejected"]


@dataclass(frozen=True)
class CryptoSignal:
    """One coded crypto signal, and how much to believe it before running it."""

    id: str
    title: str
    provenance: str
    """`paper`, `literature` or `practitioner`.

    - `paper` — rules read from a specific peer-reviewed publication.
    - `literature` — the effect is documented academically; the exact
      parameters here are ours.
    - `practitioner` — widely used, no academic validation found. Not a
      dismissal: untested is a measurable state, and measuring it is the job.
    """

    source: str
    published: str
    logic: tuple[str, ...]
    detect: Detect


# --- helpers ----------------------------------------------------------------


def _vwap(bars: Sequence[Candle]) -> float | None:
    """Volume-weighted average price over the given bars.

    Returns None rather than falling back to a simple mean when volume is
    absent. A "VWAP" computed without volume is just a moving average wearing
    its name, and every conclusion drawn from it would be about the wrong
    indicator.
    """
    volume = sum(bar.volume for bar in bars)
    if volume <= 0:
        return None
    return sum(((b.high + b.low + b.close) / 3.0) * b.volume for b in bars) / volume
