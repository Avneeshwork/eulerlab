"""Four momentum and reversal refinements with published out-of-sample evidence.

Research 113, batch 3. Chosen because each has been replicated outside the US
and in emerging markets, unlike the textbook chart rules of batches 1 and 2:

- Frog-in-the-pan momentum: Da, Gurun & Warachka (2014), RFS 27(7); confirmed
  across developed and emerging markets by Goyal, Jegadeesh & Subrahmanyam
  (Review of Finance). ID as coded in abeer555/Trend-Radar `frog_in_pan.py`.
- Residual momentum: Blitz, Huij & Martens (2011), JEF 18(3); idiosyncratic
  momentum priced across developed and emerging markets in Blitz, Hanauer &
  Vidojevic (2020).
- Volatility-scaled momentum: Barroso & Santa-Clara (2015), JFE 116(1).
- Short-term residual reversal: Blitz, Huij, Lansdorp & Verbeek (2013), JFM 16(3).

Adaptations, all stated on the cards and in research 113: long only (no
Indian short leg overnight); the point-in-time 250 most-traded stocks
(`india_papers.liquid_universe`); "months" are 21 sessions counted back from
the decision; and the residual models use the market alone (NIFTYBEES), since
no point-in-time Indian size and value factor returns are held here.
"""

from __future__ import annotations

from collections.abc import Callable

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.evidence.common import (
    HOLD,
    SAFE,
    WEEK,
    _equal,
    _percentiles,
    dividend_yield,
    dividends,
    momentum_12_1,
    monthly_returns,
    residuals,
)
from eulerlab.strategies.daily.evidence.india_alpha_low_volatility_30 import (
    STRATEGIES as _india_alpha_low_volatility_30,
)
from eulerlab.strategies.daily.evidence.india_alpha_low_volatility_30 import AlphaLowVolatility
from eulerlab.strategies.daily.evidence.india_conservative_formula import (
    STRATEGIES as _india_conservative_formula,
)
from eulerlab.strategies.daily.evidence.india_conservative_formula import ConservativeFormula
from eulerlab.strategies.daily.evidence.india_dividend_yield_30 import (
    STRATEGIES as _india_dividend_yield_30,
)
from eulerlab.strategies.daily.evidence.india_dividend_yield_30 import DividendYield
from eulerlab.strategies.daily.evidence.india_frog_in_the_pan import (
    STRATEGIES as _india_frog_in_the_pan,
)
from eulerlab.strategies.daily.evidence.india_frog_in_the_pan import (
    FrogInThePan,
    information_discreteness,
)
from eulerlab.strategies.daily.evidence.india_halloween_nifty import (
    STRATEGIES as _india_halloween_nifty,
)
from eulerlab.strategies.daily.evidence.india_halloween_nifty import WINTER, Halloween
from eulerlab.strategies.daily.evidence.india_high_volume_premium import (
    HOLD_WEEKS,
    REFERENCE_WEEKS,
    HighVolumePremium,
    high_volume_week,
)
from eulerlab.strategies.daily.evidence.india_high_volume_premium import (
    STRATEGIES as _india_high_volume_premium,
)
from eulerlab.strategies.daily.evidence.india_industry_momentum import (
    STRATEGIES as _india_industry_momentum,
)
from eulerlab.strategies.daily.evidence.india_industry_momentum import IndustryMomentum, industries
from eulerlab.strategies.daily.evidence.india_ma_distance import STRATEGIES as _india_ma_distance
from eulerlab.strategies.daily.evidence.india_ma_distance import MovingAverageDistance, ma_distance
from eulerlab.strategies.daily.evidence.india_residual_momentum import (
    STRATEGIES as _india_residual_momentum,
)
from eulerlab.strategies.daily.evidence.india_residual_momentum import ResidualMomentum
from eulerlab.strategies.daily.evidence.india_residual_reversal import (
    STRATEGIES as _india_residual_reversal,
)
from eulerlab.strategies.daily.evidence.india_residual_reversal import ResidualReversal
from eulerlab.strategies.daily.evidence.india_scaled_momentum import (
    STRATEGIES as _india_scaled_momentum,
)
from eulerlab.strategies.daily.evidence.india_scaled_momentum import ScaledMomentum, _book_returns
from eulerlab.strategies.daily.evidence.india_volatility_target_nifty import (
    STRATEGIES as _india_volatility_target_nifty,
)
from eulerlab.strategies.daily.evidence.india_volatility_target_nifty import VolatilityTarget
from eulerlab.strategies.daily.evidence.nse_github_stocks_on_the_move import (
    STRATEGIES as _nse_github_stocks_on_the_move,
)
from eulerlab.strategies.daily.evidence.nse_github_stocks_on_the_move import (
    StocksOnTheMove,
    _atr20,
    clenow_score,
)
from eulerlab.strategies.daily.evidence.nse_github_weinstein_stage2 import (
    STRATEGIES as _nse_github_weinstein_stage2,
)
from eulerlab.strategies.daily.evidence.nse_github_weinstein_stage2 import (
    WeinsteinStageTwo,
    mansfield_rs,
    stage_two,
)
from eulerlab.strategies.daily.india_papers import PaperStrategy

STRATEGIES: tuple[PaperStrategy, ...] = (
    *_india_frog_in_the_pan,
    *_india_residual_momentum,
    *_india_scaled_momentum,
    *_india_residual_reversal,
    *_india_ma_distance,
    *_india_high_volume_premium,
    *_india_industry_momentum,
    *_india_conservative_formula,
    *_nse_github_stocks_on_the_move,
    *_india_alpha_low_volatility_30,
    *_nse_github_weinstein_stage2,
    *_india_halloween_nifty,
    *_india_volatility_target_nifty,
    *_india_dividend_yield_30,
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}


__all__ = [
    "BUILDERS",
    "BY_ID",
    "HOLD",
    "HOLD_WEEKS",
    "REFERENCE_WEEKS",
    "SAFE",
    "STRATEGIES",
    "WEEK",
    "WINTER",
    "AlphaLowVolatility",
    "ConservativeFormula",
    "DividendYield",
    "FrogInThePan",
    "Halloween",
    "HighVolumePremium",
    "IndustryMomentum",
    "MovingAverageDistance",
    "ResidualMomentum",
    "ResidualReversal",
    "ScaledMomentum",
    "StocksOnTheMove",
    "VolatilityTarget",
    "WeinsteinStageTwo",
    "_atr20",
    "_book_returns",
    "_equal",
    "_percentiles",
    "clenow_score",
    "dividend_yield",
    "dividends",
    "high_volume_week",
    "industries",
    "information_discreteness",
    "ma_distance",
    "mansfield_rs",
    "momentum_12_1",
    "monthly_returns",
    "residuals",
    "stage_two",
]
