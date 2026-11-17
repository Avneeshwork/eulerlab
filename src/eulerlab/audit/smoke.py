"""Does every registered strategy actually run.

A strategy can be declared, documented, listed in the console and completely
unrunnable, and nothing notices until someone clicks it. That has happened:
eleven coded signals were unreachable from the interface because the batch
runner refused anything that was not a `Strategy` subclass.

This does not check that a strategy is any good. It checks that invoking it
returns something of the right shape instead of raising, which is the weakest
useful claim and the one nothing else makes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eulerlab.audit import Finding, Severity
from eulerlab.intraday.tweezer import Candle

BARS = 400
"""Enough for the longest declared lookback, and small enough to stay fast."""


def _candles() -> list[Candle]:
    """A synthetic session with movement in it.

    Deliberately not flat: a constant series makes every dispersion zero, so
    half the signals return "no dispersion" and the check passes without
    reaching the code it is meant to exercise.
    """
    start = datetime(2026, 8, 20, 9, 15, tzinfo=UTC)
    out: list[Candle] = []
    for step in range(BARS):
        drift = (step % 23) * 0.4 - 4.0
        price = 100.0 + drift
        out.append(
            Candle(
                ts=start + timedelta(minutes=step),
                open=price,
                high=price + 0.3,
                low=price - 0.3,
                close=price + (0.1 if step % 3 else -0.1),
                volume=1000 + (step % 7) * 250,
            )
        )
    return out


def run() -> tuple[list[Finding], int]:
    """Invoke every registered strategy once."""
    from eulerlab.intraday.paper_scan import ALL_SIGNALS
    from eulerlab.intraday.tweezer import Plan, Rejected
    from eulerlab.strategies.daily.published import BUILDERS
    from eulerlab.strategies.intraday.papers import PaperRules

    findings: list[Finding] = []
    candles = _candles()
    checked = 0

    for strategy_id in sorted(ALL_SIGNALS):
        checked += 1
        detect = getattr(ALL_SIGNALS[strategy_id], "detect", None)
        if detect is None:
            findings.append(
                Finding(
                    rule="strategy-unrunnable",
                    severity=Severity.FAIL,
                    message=f"{strategy_id} is registered with no detect function",
                    because="a strategy in the console that cannot be invoked",
                )
            )
            continue
        try:
            outcome = detect(candles, PaperRules(), 1_000_000.0)
        except Exception as exc:
            findings.append(
                Finding(
                    rule="strategy-raises",
                    severity=Severity.FAIL,
                    message=f"{strategy_id} raised {type(exc).__name__}: {exc}",
                    because="a strategy in the console that cannot be invoked",
                )
            )
            continue
        if not isinstance(outcome, Plan | Rejected):
            findings.append(
                Finding(
                    rule="strategy-shape",
                    severity=Severity.FAIL,
                    message=(
                        f"{strategy_id} returned {type(outcome).__name__}, not a Plan or a Rejected"
                    ),
                    because="the scanner branches on exactly these two",
                )
            )

    for name, builder in sorted(BUILDERS.items()):
        checked += 1
        try:
            strategy = builder()
        except Exception as exc:
            findings.append(
                Finding(
                    rule="strategy-raises",
                    severity=Severity.FAIL,
                    message=f"{name} could not be built: {type(exc).__name__}: {exc}",
                    because="a strategy in the console that cannot be invoked",
                )
            )
            continue
        if not hasattr(strategy, "target_weights"):
            findings.append(
                Finding(
                    rule="strategy-shape",
                    severity=Severity.FAIL,
                    message=f"{name} built an object with no target_weights",
                    because="the daily engine calls exactly this",
                )
            )
    return findings, checked
