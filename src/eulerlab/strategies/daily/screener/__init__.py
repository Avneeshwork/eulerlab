"""Models for the stock screener: long-term and swing, each one strategy on the common engine (ADR-136).

Built on what already works here, as the operator asked: the long-term models
start from Sharpe momentum and 12-1 momentum (the best stored daily strategies,
HISTORY #44) and add what research 150 says momentum lacks in India: quality
(Jacob, Pradeep and Varma 2022), value (Asness, Moskowitz and Pedersen 2013),
the F-score (Piotroski 2000), and a tree model over all of them (Gu, Kelly and
Xiu 2020). The swing models add a trend filter to the RSI-2 dip (Connors) and
volume to the 52-week high (George and Hwang 2004). Long-term models rebalance
monthly (21 sessions, Piotroski quarterly as its paper does) and swing models
weekly (5 sessions), as the operator set. All settings were fixed on
2026-11-04 before any result was seen; each configuration is one hypothesis
(H-0030 to H-0035).

Every model trades only the 250 most-traded stocks as of each date
(`india_papers.liquid_universe`) and decides on the view the engine hands it,
which holds only the past: fundamentals enter through
`fundamentals.annual.known`, i.e. 90 days after each year end (A-107), with
per-share values put into the decision date's units by `units`.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers import PaperStrategy
from eulerlab.strategies.daily.screener.common import (
    _TOPDOWN_FUNNEL,
    BLENDS,
    FEATURES,
    LONG,
    LONG_LOOKBACK,
    SECTOR_CAP,
    SLOTS,
    SWING,
    TOP,
    Blend,
    BreakoutVolume,
    TopSectorsOnly,
    TrendPullback,
    _blend_builder,
    _capped,
    _div,
    _factors,
    _mean_of,
    _sma,
    _top,
    _universe_facts,
    _z,
    facts,
    fscore,
    quality,
    rsi,
    units,
)
from eulerlab.strategies.daily.screener.screen_52w_breakout import SPECS as _screen_52w_breakout
from eulerlab.strategies.daily.screener.screen_consensus_3of5 import CONSENSUS_PARTS, Consensus
from eulerlab.strategies.daily.screener.screen_consensus_3of5 import SPECS as _screen_consensus_3of5
from eulerlab.strategies.daily.screener.screen_piotroski import SPECS as _screen_piotroski
from eulerlab.strategies.daily.screener.screen_piotroski import Piotroski
from eulerlab.strategies.daily.screener.screen_quality_momentum import (
    SPECS as _screen_quality_momentum,
)
from eulerlab.strategies.daily.screener.screen_quality_momentum import QualityMomentum
from eulerlab.strategies.daily.screener.screen_topdown_breakout import (
    SPECS as _screen_topdown_breakout,
)
from eulerlab.strategies.daily.screener.screen_topdown_discount import (
    SPECS as _screen_topdown_discount,
)
from eulerlab.strategies.daily.screener.screen_topdown_discount import (
    TopDownDiscount,
    industry_relative,
)
from eulerlab.strategies.daily.screener.screen_topdown_pullback import (
    SPECS as _screen_topdown_pullback,
)
from eulerlab.strategies.daily.screener.screen_topdown_quality_momentum import (
    SPECS as _screen_topdown_quality_momentum,
)
from eulerlab.strategies.daily.screener.screen_topdown_quality_momentum import (
    TopDownQualityMomentum,
)
from eulerlab.strategies.daily.screener.screen_topdown_sectors import (
    SPECS as _screen_topdown_sectors,
)
from eulerlab.strategies.daily.screener.screen_topdown_sectors import TopDownSectors
from eulerlab.strategies.daily.screener.screen_tree_ranker import SPECS as _screen_tree_ranker
from eulerlab.strategies.daily.screener.screen_tree_ranker import TreeRanker, features
from eulerlab.strategies.daily.screener.screen_trend_pullback import SPECS as _screen_trend_pullback
from eulerlab.strategies.daily.screener.screen_value_momentum_quality import (
    SPECS as _screen_value_momentum_quality,
)
from eulerlab.strategies.daily.screener.screen_value_momentum_quality import ValueMomentumQuality

# --- the registry ---------------------------------------------------------------------------------


SPECS: tuple[tuple[PaperStrategy, str], ...] = (
    *_screen_quality_momentum,
    *_screen_value_momentum_quality,
    *_screen_piotroski,
    *_screen_tree_ranker,
    *_screen_trend_pullback,
    *_screen_52w_breakout,
)
SPECS = SPECS + tuple(
    (
        PaperStrategy(
            id=bid,
            title=title,
            paper="gu-kelly-xiu-2020-ml-asset-pricing"
            if kind == LONG
            else "github-2026-trend-radar-minervini",
            citation="Fixed-weight blend of registered strategies (ADR-137)",
            summary=f"{title}; one book, rebalanced every {every} sessions.",
            logic=(
                *(f"{pid}: {share:.0%} of capital" for pid, share in parts),
                f"Rebalanced every {every} sessions; shares fixed, not fitted.",
            ),
            lookback=LONG_LOOKBACK,
            build=_blend_builder(bid, parts, every),
        ),
        kind,
    )
    for bid, title, kind, parts, every in BLENDS
)

SPECS = (
    *SPECS,
    *_screen_consensus_3of5,
)

SPECS = (
    *SPECS,
    *_screen_topdown_sectors,
    *_screen_topdown_quality_momentum,
    *_screen_topdown_discount,
    *_screen_topdown_pullback,
    *_screen_topdown_breakout,
)

STRATEGIES = tuple(s for s, _ in SPECS)
KIND = {s.id: k for s, k in SPECS}
BY_ID = {s.id: s for s in STRATEGIES}
BUILDERS = {s.id: s.build for s in STRATEGIES}


__all__ = [
    "BLENDS",
    "BUILDERS",
    "BY_ID",
    "CONSENSUS_PARTS",
    "FEATURES",
    "KIND",
    "LONG",
    "LONG_LOOKBACK",
    "SECTOR_CAP",
    "SLOTS",
    "SPECS",
    "STRATEGIES",
    "SWING",
    "TOP",
    "_TOPDOWN_FUNNEL",
    "Blend",
    "BreakoutVolume",
    "Consensus",
    "Piotroski",
    "QualityMomentum",
    "TopDownDiscount",
    "TopDownQualityMomentum",
    "TopDownSectors",
    "TopSectorsOnly",
    "TreeRanker",
    "TrendPullback",
    "ValueMomentumQuality",
    "_blend_builder",
    "_capped",
    "_div",
    "_factors",
    "_mean_of",
    "_sma",
    "_top",
    "_universe_facts",
    "_z",
    "facts",
    "features",
    "fscore",
    "industry_relative",
    "quality",
    "rsi",
    "units",
]
