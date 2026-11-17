"""Five daily strategies from public GitHub repositories, run on NSE as written.

Research 113. The earlier GitHub rounds (research 088-111) ported intraday
rules to five NSE stocks; every one lost to intraday costs, which take more
than the 2-8 bp a trade those rules earn. These five trade on daily bars,
hold for days to months and pay delivery costs a few times a month at most.

Each follows its repository's rule as stated in the code (fetched 2026-10-18,
recorded in research 113), adapted only where NSE or this engine requires:

- **The engine fills at the next session's close.** Repositories that trade at
  the signal's own close are one day later here; said per strategy.
- **Stock rules run on the point-in-time 250 most-traded stocks**
  (`india_papers.liquid_universe`), the house convention that keeps today's
  winners out of the past.
- **Position rules (enter on one condition, leave on another)** are replayed
  over the last `STATE_WINDOW` sessions at every decision, so the strategy
  needs no memory between calls and a backtest and a paper run agree. A
  position older than the window is treated as opened inside it; the
  approximation is stated in research 113.
- **Long only.** Every rule here is long only in its repository.
"""

from __future__ import annotations

from collections.abc import Callable

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.github.common import (
    STATE_WINDOW,
    Age,
    PositionRule,
    Signal,
    _age,
    _closes,
    crossing_rule,
    in_trade,
)
from eulerlab.strategies.daily.github.nse_github_dual_momentum_etf import DUAL, DualMomentum, _ret
from eulerlab.strategies.daily.github.nse_github_dual_momentum_etf import (
    STRATEGIES as _nse_github_dual_momentum_etf,
)
from eulerlab.strategies.daily.github.nse_github_faber_taa_etf import CASH, FABER, FaberTAA
from eulerlab.strategies.daily.github.nse_github_faber_taa_etf import (
    STRATEGIES as _nse_github_faber_taa_etf,
)
from eulerlab.strategies.daily.github.nse_github_golden_cross import (
    STRATEGIES as _nse_github_golden_cross,
)
from eulerlab.strategies.daily.github.nse_github_golden_cross import golden_cross_rule
from eulerlab.strategies.daily.github.nse_github_ibs_niftybees import (
    STRATEGIES as _nse_github_ibs_niftybees,
)
from eulerlab.strategies.daily.github.nse_github_ibs_niftybees import _ibs, ibs_rule
from eulerlab.strategies.daily.github.nse_github_macd_crossover import (
    STRATEGIES as _nse_github_macd_crossover,
)
from eulerlab.strategies.daily.github.nse_github_macd_crossover import _ema, macd_rule
from eulerlab.strategies.daily.github.nse_github_minervini_template import (
    RS_WEIGHTS,
    TrendTemplate,
    rs_raw,
    trend_template,
)
from eulerlab.strategies.daily.github.nse_github_minervini_template import (
    STRATEGIES as _nse_github_minervini_template,
)
from eulerlab.strategies.daily.github.nse_github_rsi2_daily import (
    STRATEGIES as _nse_github_rsi2_daily,
)
from eulerlab.strategies.daily.github.nse_github_rsi2_daily import rsi2_rule
from eulerlab.strategies.daily.github.nse_github_supertrend_10_22 import (
    STRATEGIES as _nse_github_supertrend_10_22,
)
from eulerlab.strategies.daily.github.nse_github_supertrend_10_22 import (
    supertrend_rule,
    supertrend_up,
)
from eulerlab.strategies.daily.github.nse_github_turtle_20_10 import (
    STRATEGIES as _nse_github_turtle_20_10,
)
from eulerlab.strategies.daily.github.nse_github_turtle_20_10 import prior_extreme, turtle_rule
from eulerlab.strategies.daily.india_papers import PaperStrategy

# --- the registry entries -----------------------------------------------------------


STRATEGIES: tuple[PaperStrategy, ...] = (
    *_nse_github_rsi2_daily,
    *_nse_github_ibs_niftybees,
    *_nse_github_turtle_20_10,
    *_nse_github_minervini_template,
    *_nse_github_dual_momentum_etf,
)

STRATEGIES += (
    *_nse_github_golden_cross,
    *_nse_github_supertrend_10_22,
    *_nse_github_macd_crossover,
    *_nse_github_faber_taa_etf,
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}


__all__ = [
    "BUILDERS",
    "BY_ID",
    "CASH",
    "DUAL",
    "FABER",
    "RS_WEIGHTS",
    "STATE_WINDOW",
    "STRATEGIES",
    "Age",
    "DualMomentum",
    "FaberTAA",
    "PositionRule",
    "Signal",
    "TrendTemplate",
    "_age",
    "_closes",
    "_ema",
    "_ibs",
    "_ret",
    "crossing_rule",
    "golden_cross_rule",
    "ibs_rule",
    "in_trade",
    "macd_rule",
    "prior_extreme",
    "rs_raw",
    "rsi2_rule",
    "supertrend_rule",
    "supertrend_up",
    "trend_template",
    "turtle_rule",
]
