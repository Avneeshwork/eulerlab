"""The deployed book as one thing: roll-up, value at risk, stress, exposure (ADR-071).

Operator, 2026-10-14: "a screen which shows risk on current trading
strategies: current VaR, strategy distribution, maximum risk, allocation in
different strategies". Until now each deployment was shown alone and the only
risk figures were the kill switch's counts (research 079).

Everything here is arithmetic on values handed in: the deployments' stored
books, a table of adjusted closes, sectors. Nothing reads a file, places an
order or stops one. `api/risk_routes.py` gathers the inputs.

### How the risk numbers are made

A deployment is days old, so its own returns cannot give a value at risk.
Instead **today's holdings are run through the last `WINDOW` trading days**:
for each past day, what would this exact book have made or lost? That gives a
profit-and-loss history for the book as it stands now, and every figure below
is read from it.

- **VaR** at 95% is the loss that history exceeded on one day in twenty
  (`quantile_loss`, nearest rank). **Expected shortfall** is the average loss
  on those days.
- **Three methods**, shown side by side: that history as it is; a normal
  curve with the history's mean and spread; and a normal curve whose spread
  weights recent days more (`LAMBDA`, the RiskMetrics convention).
- **Component VaR** splits the book's VaR between deployments in proportion
  to each one's covariance with the book. The parts sum to the whole.
- **Stress** moves each holding by a stated shock, through its beta to the
  Nifty where the shock is a market move.

What this cannot see: a holding with no price on a past day counts as flat
that day (`coverage` says how much of the book that is); a deployment that
holds nothing at the close has no risk here even if it trades overnight;
nothing is assumed about liquidity, so a loss is what the closes say.
"""

from __future__ import annotations

from eulerlab.risk.book.beta import beta, name_beta
from eulerlab.risk.book.common import (
    LAMBDA,
    MARKET,
    MIN_BAND_DAYS,
    MIN_DAYS,
    MIN_GAP_NIGHTS,
    TRADING_DAYS,
    WINDOW,
    Z,
)
from eulerlab.risk.book.correlation import components, correlation, covariance
from eulerlab.risk.book.curves import combined_curve, drawdown, histogram, today_pnl
from eulerlab.risk.book.exposure import by_name, by_sector
from eulerlab.risk.book.gap import gap_summary
from eulerlab.risk.book.growth import growth
from eulerlab.risk.book.history import returns_of, rule_pnl, scenario_pnl, window_days
from eulerlab.risk.book.holdings import Book, GapRule, Holding, book_from_state
from eulerlab.risk.book.stress import limit_row, stress
from eulerlab.risk.book.var import _mean_sd, _normal_tail, quantile_loss, recent_sd, var_table
from eulerlab.risk.book.vs_backtest import against_backtest, backtest_band

__all__ = [
    "LAMBDA",
    "MARKET",
    "MIN_BAND_DAYS",
    "MIN_DAYS",
    "MIN_GAP_NIGHTS",
    "TRADING_DAYS",
    "WINDOW",
    "Book",
    "GapRule",
    "Holding",
    "Z",
    "_mean_sd",
    "_normal_tail",
    "against_backtest",
    "backtest_band",
    "beta",
    "book_from_state",
    "by_name",
    "by_sector",
    "combined_curve",
    "components",
    "correlation",
    "covariance",
    "drawdown",
    "gap_summary",
    "growth",
    "histogram",
    "limit_row",
    "name_beta",
    "quantile_loss",
    "recent_sd",
    "returns_of",
    "rule_pnl",
    "scenario_pnl",
    "stress",
    "today_pnl",
    "var_table",
    "window_days",
]
