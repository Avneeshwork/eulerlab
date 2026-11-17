"""Strategies from papers on Indian equities, built as their papers state them.

Each builder at the bottom cites one paper in `research/papers/` and follows its
stated rules as far as this platform's data allows. Where a paper's design
cannot be run here, the adaptation is stated in the paper's red flags and in
the builder's docstring, never silently:

- **Long only.** Every long-short factor in these papers is tested on its long
  leg. Cash equities cannot be held short overnight in India; a short leg
  would need single-stock futures, which exist for about 200 names and which
  the daily engine does not trade.
- **Equal weights.** The panel has no share counts, so market-cap weights and
  size buckets are unavailable. Papers that value-weight are run equal-weighted.
- **The universe is point-in-time.** Cross-sectional papers run on the 250
  most-traded stocks *as of each decision date* (median turnover over the
  previous 60 sessions), chosen from the whole panel. The named `nifty250`
  universe is today's list applied to all of history, which hands every past
  backtest the stocks that later became liquid — and those are largely the
  stocks that rose. Run on it, the illiquid decile returned +4,200% over ten
  years; see HISTORY #16.
- **ETFs are excluded** from every cross-sectional rank: an index fund is not a
  stock, and the most-traded list would otherwise include NIFTYBEES.

Calendar strategies trade NIFTYBEES, the Nifty 50 ETF, as the investable
stand-in for the index the paper studied. They read the exchange calendar from
the panel's own trading days, which is known in advance in reality (the
exchange publishes it) but here also includes any unscheduled closure.
"""

from __future__ import annotations

from collections.abc import Callable

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.india_papers.common import (
    INDEX_ETF,
    INDEX_ONLY,
    LIQUID_TOP,
    LIQUIDITY_WINDOW,
    MONTH,
    YEAR,
    AbsoluteMomentum,
    DoubleSort,
    IndexCalendar,
    PaperStrategy,
    RankTop,
    Score,
    _calendar,
    _is_fund,
    _monthly_closes,
    _returns,
    _sd,
    amihud_illiquidity,
    liquid_universe,
    momentum,
    monthly_volatility,
    sharpe_momentum,
    sharpe_momentum_over,
    trading_calendar,
)
from eulerlab.strategies.daily.india_papers.india_52w_high import STRATEGIES as _india_52w_high
from eulerlab.strategies.daily.india_papers.india_52w_high import nearness_to_52w_high
from eulerlab.strategies.daily.india_papers.india_bab_low_beta import (
    STRATEGIES as _india_bab_low_beta,
)
from eulerlab.strategies.daily.india_papers.india_bab_low_beta import LowBeta
from eulerlab.strategies.daily.india_papers.india_bb_rsi import STRATEGIES as _india_bb_rsi
from eulerlab.strategies.daily.india_papers.india_bb_rsi import LiquidBuilt, _bb_rsi
from eulerlab.strategies.daily.india_papers.india_big_fall_reversal import (
    STRATEGIES as _india_big_fall_reversal,
)
from eulerlab.strategies.daily.india_papers.india_big_fall_reversal import BigFallReversal
from eulerlab.strategies.daily.india_papers.india_budget_days import (
    STRATEGIES as _india_budget_days,
)
from eulerlab.strategies.daily.india_papers.india_budget_days import UNION_BUDGETS, around_budget
from eulerlab.strategies.daily.india_papers.india_bullish_candles import (
    BULLISH_CANDLES,
    CandleHold,
    _fell,
    _real_bar,
    bullish_engulfing,
    hammer,
    rising_window,
)
from eulerlab.strategies.daily.india_papers.india_bullish_candles import (
    STRATEGIES as _india_bullish_candles,
)
from eulerlab.strategies.daily.india_papers.india_contrarian_36m import (
    STRATEGIES as _india_contrarian_36m,
)
from eulerlab.strategies.daily.india_papers.india_december import STRATEGIES as _india_december
from eulerlab.strategies.daily.india_papers.india_december import december
from eulerlab.strategies.daily.india_papers.india_expiry_day import STRATEGIES as _india_expiry_day
from eulerlab.strategies.daily.india_papers.india_expiry_day import (
    _expiry_weekday,
    is_monthly_expiry,
)
from eulerlab.strategies.daily.india_papers.india_high_vol60 import STRATEGIES as _india_high_vol60
from eulerlab.strategies.daily.india_papers.india_illiquid_decile import (
    STRATEGIES as _india_illiquid_decile,
)
from eulerlab.strategies.daily.india_papers.india_illiquid_winners import (
    STRATEGIES as _india_illiquid_winners,
)
from eulerlab.strategies.daily.india_papers.india_liquid_winners import (
    STRATEGIES as _india_liquid_winners,
)
from eulerlab.strategies.daily.india_papers.india_liquid_winners import median_turnover
from eulerlab.strategies.daily.india_papers.india_low_max_l5 import STRATEGIES as _india_low_max_l5
from eulerlab.strategies.daily.india_papers.india_low_max_l5 import max_last5
from eulerlab.strategies.daily.india_papers.india_low_tvol36 import STRATEGIES as _india_low_tvol36
from eulerlab.strategies.daily.india_papers.india_macd_buy import STRATEGIES as _india_macd_buy
from eulerlab.strategies.daily.india_papers.india_macd_buy import _macd_buy
from eulerlab.strategies.daily.india_papers.india_midcap_follows_largecap import (
    STRATEGIES as _india_midcap_follows_largecap,
)
from eulerlab.strategies.daily.india_papers.india_midcap_follows_largecap import LeadLag
from eulerlab.strategies.daily.india_papers.india_momentum_3x6 import (
    STRATEGIES as _india_momentum_3x6,
)
from eulerlab.strategies.daily.india_papers.india_momentum_12_noskip import (
    STRATEGIES as _india_momentum_12_noskip,
)
from eulerlab.strategies.daily.india_papers.india_monday_wednesday import (
    STRATEGIES as _india_monday_wednesday,
)
from eulerlab.strategies.daily.india_papers.india_monday_wednesday import monday_or_wednesday
from eulerlab.strategies.daily.india_papers.india_nifty_sma60 import (
    STRATEGIES as _india_nifty_sma60,
)
from eulerlab.strategies.daily.india_papers.india_nifty_sma60 import _nifty_sma60
from eulerlab.strategies.daily.india_papers.india_pair_bharatforg_ashokley import (
    STRATEGIES as _india_pair_bharatforg_ashokley,
)
from eulerlab.strategies.daily.india_papers.india_pair_bharatforg_ashokley import PairRatio
from eulerlab.strategies.daily.india_papers.india_physical_momentum import (
    STRATEGIES as _india_physical_momentum,
)
from eulerlab.strategies.daily.india_papers.india_physical_momentum import mean_over_sd
from eulerlab.strategies.daily.india_papers.india_post_holiday import (
    STRATEGIES as _india_post_holiday,
)
from eulerlab.strategies.daily.india_papers.india_post_holiday import post_holiday
from eulerlab.strategies.daily.india_papers.india_sector_rotation import (
    SECTOR_INDICES,
    SectorRotation,
    _close_before,
)
from eulerlab.strategies.daily.india_papers.india_sector_rotation import (
    STRATEGIES as _india_sector_rotation,
)
from eulerlab.strategies.daily.india_papers.india_sharpe_momentum import (
    STRATEGIES as _india_sharpe_momentum,
)
from eulerlab.strategies.daily.india_papers.india_sharpe_momentum_opt import (
    STRATEGIES as _india_sharpe_momentum_opt,
)
from eulerlab.strategies.daily.india_papers.india_tsmom import STRATEGIES as _india_tsmom
from eulerlab.strategies.daily.india_papers.india_tsmom_risk_managed import (
    STRATEGIES as _india_tsmom_risk_managed,
)
from eulerlab.strategies.daily.india_papers.india_turn_of_month import (
    STRATEGIES as _india_turn_of_month,
)
from eulerlab.strategies.daily.india_papers.india_turn_of_month import turn_of_month
from eulerlab.strategies.daily.india_papers.india_weekly_momentum import (
    STRATEGIES as _india_weekly_momentum,
)
from eulerlab.strategies.daily.india_papers.india_wml_12_1 import STRATEGIES as _india_wml_12_1

STRATEGIES: tuple[PaperStrategy, ...] = (
    *_india_bab_low_beta,
    *_india_high_vol60,
    *_india_low_max_l5,
    *_india_illiquid_decile,
    *_india_wml_12_1,
    *_india_low_tvol36,
    *_india_turn_of_month,
    *_india_monday_wednesday,
    *_india_expiry_day,
    *_india_pair_bharatforg_ashokley,
    *_india_macd_buy,
    *_india_post_holiday,
    *_india_momentum_3x6,
    *_india_sharpe_momentum,
    *_india_sharpe_momentum_opt,
    *_india_momentum_12_noskip,
    *_india_52w_high,
    *_india_weekly_momentum,
    *_india_illiquid_winners,
    *_india_liquid_winners,
    *_india_tsmom,
    *_india_tsmom_risk_managed,
    *_india_budget_days,
    *_india_nifty_sma60,
    *_india_physical_momentum,
    *_india_big_fall_reversal,
    *_india_contrarian_36m,
    *_india_december,
    *_india_bb_rsi,
    *_india_sector_rotation,
    *_india_bullish_candles,
    *_india_midcap_follows_largecap,
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}


__all__ = [
    "BUILDERS",
    "BULLISH_CANDLES",
    "BY_ID",
    "INDEX_ETF",
    "INDEX_ONLY",
    "LIQUIDITY_WINDOW",
    "LIQUID_TOP",
    "MONTH",
    "SECTOR_INDICES",
    "STRATEGIES",
    "UNION_BUDGETS",
    "YEAR",
    "AbsoluteMomentum",
    "BigFallReversal",
    "CandleHold",
    "DoubleSort",
    "IndexCalendar",
    "LeadLag",
    "LiquidBuilt",
    "LowBeta",
    "PairRatio",
    "PaperStrategy",
    "RankTop",
    "Score",
    "SectorRotation",
    "_bb_rsi",
    "_calendar",
    "_close_before",
    "_expiry_weekday",
    "_fell",
    "_is_fund",
    "_macd_buy",
    "_monthly_closes",
    "_nifty_sma60",
    "_real_bar",
    "_returns",
    "_sd",
    "amihud_illiquidity",
    "around_budget",
    "bullish_engulfing",
    "december",
    "hammer",
    "is_monthly_expiry",
    "liquid_universe",
    "max_last5",
    "mean_over_sd",
    "median_turnover",
    "momentum",
    "monday_or_wednesday",
    "monthly_volatility",
    "nearness_to_52w_high",
    "post_holiday",
    "rising_window",
    "sharpe_momentum",
    "sharpe_momentum_over",
    "trading_calendar",
    "turn_of_month",
]
