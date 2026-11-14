"""What every intraday screen computes the same way: its summary, its charges, two indicators.

Each screen used to carry its own copy. Fifteen copies of the daily summary,
seven of the intraday charge and two each of EMA and RSI had drifted apart only
in variable names; one bug fixed in one copy would have stayed in the other
fourteen. The rules themselves stay in their own modules. This holds only the
arithmetic they share, unchanged, so no stored result moves.

Not here on purpose: the two ATRs (`github_momentum_burst_screen` smooths
Wilder-style, `hikkake_screen` takes a plain mean). They are different rules,
and folding them together would change one screen's numbers.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Sequence
from datetime import date
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side

TRADING_DAYS = 252
"""Annualisation for a daily Sharpe."""


def daily_stats(values: Sequence[float]) -> dict[str, Any]:
    """Days, compounded total return, annualised Sharpe and worst drawdown.

    Sharpe is None for a flat or one-day series rather than a division by zero.
    """
    equity = peak = 1.0
    drawdown = 0.0
    for change in values:
        equity *= 1.0 + change
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "days": len(values),
        "total_return": round(equity - 1.0, 6),
        "sharpe": round(statistics.fmean(values) / deviation * math.sqrt(TRADING_DAYS), 3)
        if deviation
        else None,
        "max_drawdown": round(drawdown, 6),
    }


@lru_cache(maxsize=1 << 20)  # pure, and the same fill recurs across a population (#167)
def intraday_fee(price: float, quantity: int, side: Side, day: date) -> float:
    """NSE intraday equity charges for one fill, from the time-versioned schedule."""
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=quantity,
        side=side,
        day=day,
        segment=Segment.EQUITY_INTRADAY,
    )


def round_trip_cost(
    entry: float,
    exit_: float,
    quantity: int,
    day: date,
    direction: int,
    *,
    slippage_bps: float,
) -> float:
    """Charges on both fills plus slippage on both, for a long (+1) or short (-1) trade."""
    entry_side = Side.BUY if direction > 0 else Side.SELL
    exit_side = Side.SELL if direction > 0 else Side.BUY
    fees = intraday_fee(entry, quantity, entry_side, day)
    fees += intraday_fee(exit_, quantity, exit_side, day)
    return fees + (entry + exit_) * quantity * slippage_bps / 10_000.0


def ema(values: Sequence[float], period: int) -> list[float]:
    """Exponential average seeded at the first value; one output per input."""
    alpha = 2.0 / (period + 1.0)
    result: list[float] = []
    current = values[0]
    for value in values:
        current += alpha * (value - current)
        result.append(current)
    return result


def rsi(values: Sequence[float], period: int) -> list[float | None]:
    """Wilder RSI with a full warmup: None until `period` changes have been seen."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    changes = [right - left for left, right in pairwise(values)]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = statistics.fmean(gains[:period])
    avg_loss = statistics.fmean(losses[:period])

    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    out[period] = value(avg_gain, avg_loss)
    for index in range(period + 1, len(values)):
        avg_gain = ((period - 1) * avg_gain + gains[index - 1]) / period
        avg_loss = ((period - 1) * avg_loss + losses[index - 1]) / period
        out[index] = value(avg_gain, avg_loss)
    return out


def write_and_print(output: Path, result: dict[str, Any]) -> int:
    """The tail every screen's `main` shared (ADR-161): write the JSON, print run 0."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run = result["runs"][0]
    print(
        f"wrote {output}: {run['trades']} trades, gross "
        f"{run['gross']['total_return']:.2%}, net {run['net']['total_return']:.2%}"
    )
    return 0
