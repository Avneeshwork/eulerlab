"""IBS reversion on NIFTYBEES (GitHub rule).

Source: toniker10/SPY-IBS-Mean-Reversion-Strategy (GitHub, 2026).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.github.common import STATE_WINDOW, Age, PositionRule, _age, in_trade
from eulerlab.strategies.daily.india_papers import INDEX_ETF, PaperStrategy


def _ibs(row: PanelRow) -> float:
    _, high, low, close = row.ohlc()
    return (close - low) / (high - low) if high > low else 0.5


def ibs_rule(rows: Sequence[PanelRow]) -> Age:
    """toniker10/SPY-IBS-Mean-Reversion-Strategy: in when IBS < 0.20, out when IBS > 0.80.
    IBS = (close - low) / (high - low); a day with no range counts 0.5, as there."""
    n = len(rows)
    return _age(
        n,
        in_trade(
            n,
            lambda i: _ibs(rows[i]) < 0.20,
            lambda i: _ibs(rows[i]) > 0.80,
            start=max(0, n - STATE_WINDOW),
        ),
    )


STRATEGIES = (
    PaperStrategy(
        "nse_github_ibs_niftybees",
        "IBS reversion on NIFTYBEES (GitHub rule)",
        "github-2026-spy-ibs-mean-reversion",
        "toniker10/SPY-IBS-Mean-Reversion-Strategy (GitHub, 2026)",
        "Buy the Nifty ETF after a close in the bottom fifth of the day's range; sell after one in the top fifth.",
        (
            "IBS = (close - low) / (high - low). In when IBS < 0.20, out when IBS > 0.80, on "
            "NIFTYBEES as the stand-in for SPY.",
            "The repository holds from the signal close; the engine fills at the next close, "
            "one session later.",
        ),
        STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_ibs_niftybees",
            ibs_rule,
            lookback=STATE_WINDOW + 5,
            slots=1,
            instruments=(INDEX_ETF,),
        ),
        "all",
        (INDEX_ETF,),
    ),
)
