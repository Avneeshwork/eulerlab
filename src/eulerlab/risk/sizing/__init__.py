"""How a strategy's money is split across the names it picks (ADR-122).

Operator, 2026-11-02: "use equal sizing with maximum limit as default can be
according to strategy if explicitly defined else from models we develop."

A strategy says *what* to hold, best first. This module says *how much* of
each, by the rule the strategy declares in `Strategy.sizing`:

- ``equal`` (the default) — the strategy's gross exposure split equally over
  its names. A slot strategy holding 4 names at 10% each keeps 10% each: the
  gross is kept, so idle cash stays idle, as the strategy designed.
- ``strategy`` — the strategy's own weights, unchanged. For strategies whose
  weights are part of the idea: Clenow's inverse ATR, betting-against-beta,
  a volatility target, a user's sandbox code.
- ``inverse_vol`` — weight proportional to 1 / sigma over the last 126 days
  (Maillard, Roncalli & Teiletche 2010; Kirby & Ostdiek 2012).
- ``hrp`` — hierarchical risk parity (Lopez de Prado 2016) on a Ledoit-Wolf
  covariance shrunk to constant correlation (Ledoit & Wolf 2004).
- ``min_variance`` — long-only minimum variance on the same covariance, each
  name at most `max_weight(k)` (Jagannathan & Ma 2003).

The caps and the affordability fit (`deploy.sizing`) still apply afterwards:
"maximum limit" is `max_weight(k)` for every rule. The evidence for the
default is research note 140: on five NSE baskets, 2016-2026, no model beat
equal rupees on Sharpe by more than noise.

A model needs history. When fewer than `MIN_DAYS` common return days exist for
the picks (a strategy with a short `lookback`, a new listing), the model falls
back to ``equal`` rather than guess.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from eulerlab.risk.sizing.capital_fit import _fit_k, fit_to_capital, ranked
from eulerlab.risk.sizing.caps import CAPS, capped, max_weight

if TYPE_CHECKING:
    from eulerlab.backtest.strategy import MarketView
from eulerlab.risk.sizing.common import (
    HISTORY_NEEDED,
    MIN_DAYS,
    MODELS,
    RULES,
    WINDOW,
    Matrix,
    Sizing,
)
from eulerlab.risk.sizing.covariance import ledoit_wolf, returns_matrix
from eulerlab.risk.sizing.equal import _equal
from eulerlab.risk.sizing.hrp import _cluster_variance, _single_linkage_order, hrp
from eulerlab.risk.sizing.inverse_vol import inverse_vol
from eulerlab.risk.sizing.min_variance import _project_capped_simplex, min_variance


def rule_of(strategy: Any) -> str:
    """The strategy's declared rule. Unknown values raise: a typo must not
    silently become equal sizing."""
    rule = str(getattr(strategy, "sizing", "equal"))
    if rule not in RULES:
        msg = (
            f"{getattr(strategy, 'name', strategy)!r} declares sizing {rule!r}; use one of {RULES}"
        )
        raise ValueError(msg)
    return rule


def fit_by_order(strategy: Any) -> bool:
    """Whether the capital fit ranks by the strategy's own order. A model's
    weights are sizes, not ranks, so a modelled book always ranks by order."""
    return bool(getattr(strategy, "ranked_by_order", False)) or rule_of(strategy) in MODELS


def size_book(weights: Mapping[str, float], view: MarketView | None, rule: str) -> dict[str, float]:
    """`weights` re-split by `rule`, keeping their order and gross exposure.

    Long weights only (the engines drop shorts first). Zero weights are
    dropped. `view` may be None for ``equal`` and ``strategy``.
    """
    if rule not in RULES:
        msg = f"unknown sizing rule {rule!r}"
        raise ValueError(msg)
    picks = {s: w for s, w in weights.items() if w > 0 and math.isfinite(w)}
    if rule == "strategy" or len(picks) <= 1:
        return picks
    gross = sum(picks.values())
    names = list(picks)
    if rule == "equal":
        return _equal(picks, gross)
    returns = returns_matrix(view, names) if view is not None else None
    if returns is None:
        return _equal(picks, gross)
    if rule == "inverse_vol":
        split = inverse_vol(returns)
    else:
        cov = ledoit_wolf(returns)
        split = hrp(cov) if rule == "hrp" else min_variance(cov, max_weight(len(names)))
    # The cap is applied here as well as in the capital fit, so a model's book
    # obeys it in Tier A too, which does not fit to capital.
    fitted = capped(
        dict(zip(names, (float(w) for w in split), strict=True)), max_weight(len(names))
    )
    return {s: gross * fitted[s] for s in names}


__all__ = [
    "CAPS",
    "HISTORY_NEEDED",
    "MIN_DAYS",
    "MODELS",
    "RULES",
    "WINDOW",
    "Matrix",
    "Sizing",
    "_cluster_variance",
    "_equal",
    "_fit_k",
    "_project_capped_simplex",
    "_single_linkage_order",
    "capped",
    "fit_by_order",
    "fit_to_capital",
    "hrp",
    "inverse_vol",
    "ledoit_wolf",
    "max_weight",
    "min_variance",
    "ranked",
    "returns_matrix",
    "rule_of",
    "size_book",
]
