"""Sector rotation, middle five, yearly (India).

Source: Sharma (2025), sector index rotation on the NSE.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date, timedelta

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import PaperStrategy

SECTOR_INDICES = (
    "Nifty Auto",
    "Nifty Bank",
    "Nifty Commodities",
    "Nifty Energy",
    "Nifty Financial Services",
    "Nifty FMCG",
    "Nifty India Consumption",
    "Nifty Infrastructure",
    "Nifty IT",
    "Nifty Media",
    "Nifty Metal",
    "Nifty Pharma",
    "Nifty PSU Bank",
    "Nifty Realty",
    "Nifty Services Sector",
)
"""Fifteen NSE sectoral and thematic indices with a close on every day since
2015 (`market_history.index_history`).

# ASSUMPTION: Sharma (2025) ranks "15 sectoral indices" without naming them in
# what was read; these are the fifteen with unbroken history here. Nifty
# Private Bank starts in 2016 and Healthcare, Consumer Durables and Oil & Gas
# have gaps, so they are left out. See A-045."""


def _close_before(rows: Sequence[PanelRow], day: date) -> float | None:
    """The last close strictly before `day`."""
    position = bisect_right(rows, day - timedelta(days=1), key=lambda r: r.day) - 1
    return rows[position].close if position >= 0 else None


class SectorRotation(Strategy):
    """Once a year, hold the indices ranked `first` to `last` on the previous
    calendar year's return, equal-weighted (Sharma 2025's "middle group").

    The instruments are the index levels themselves, run through the batch
    universe `market_history.INDEX_UNIVERSE`: there are no sector ETFs over
    this window, so the result is what an investor in a fund tracking each
    index would have had, before tracking error, at stock-delivery costs.
    """

    rebalance_every = 1
    lookback = 530
    """Two years and a margin: the view holds only `lookback` rows, and the
    rank needs the close before the start of last year. With one year the
    first close in the view stood in for it and slid forward every day, so
    the ranking changed daily and a yearly strategy traded 2,793 times."""

    def __init__(self, name: str, *, first: int = 6, last: int = 10) -> None:
        self.name = name
        self.first = first
        self.last = last
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        year = view.as_of.year
        scored: list[tuple[float, str]] = []
        for symbol in view.symbols():
            rows = view.history[symbol]
            if not rows or rows[-1].day != view.as_of:
                continue
            end = _close_before(rows, date(year, 1, 1))
            # The first year of data (2015) has no close before it; its first
            # close stands in, so 2016's rank uses 2015 from its first session.
            begin = _close_before(rows, date(year - 1, 1, 1))
            if begin is None and rows[0].day.year == year - 1:
                begin = rows[0].close
            if end is None or not begin:
                continue
            scored.append((end / begin - 1.0, symbol))
        if len(scored) < self.last:
            return {}
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen = [symbol for _, symbol in scored[self.first - 1 : self.last]]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


STRATEGIES = (
    PaperStrategy(
        "india_sector_rotation",
        "Sector rotation, middle five, yearly (India)",
        "sharma-2025-sector-rotation-india",
        "Sharma (2025), sector index rotation on the NSE",
        "Each January, hold the five sectoral indices ranked 6th to 10th on last year's return.",
        (
            "Fifteen NSE sectoral and thematic indices with history since 2015, ranked on "
            "the previous calendar year's return; ranks 6-10 equal-weighted, held a year.",
            "Run on the index levels: no sector ETFs exist over the window. Costs are "
            "stock-delivery rates, higher than a fund's.",
        ),
        530,
        lambda: SectorRotation("india_sector_rotation"),
        "nse_indices",
        SECTOR_INDICES,
    ),
)
