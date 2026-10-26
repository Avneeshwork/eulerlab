"""Strategies from the published literature.

Each one cites the paper it comes from — `docs/RESEARCH/017` holds the URLs and
fetch dates. `CLAUDE.md` forbids inventing a source, and "a well-known strategy"
is not a source.

**These are published findings, not predictions about Indian equities.** Every
paper behind them is predominantly US evidence over windows ending years ago.
Momentum is the most replicated result in the literature and its premium still
decayed after publication. Nothing here has been backtested by this project,
and when it is, the noise bar applies.

Most of these are a `RankAndHold` over an existing feature — which is the
honest implementation, not a shortcut. The feature library was built from the
same literature, so "implement the low-volatility anomaly" genuinely is
"rank on `low_volatility` and hold the top N". Writing a bespoke class per
paper would produce ten copies of one loop and hide that fact.

`Composite` is the exception: it is not a rank over one feature, so it gets a
class.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.features.library import BY_NAME, Feature


class Composite(Strategy):
    """Rank on several features at once, averaging the ranks.

    Ranks rather than raw values, because the features are in incompatible
    units — a log turnover and a negated drawdown cannot be averaged and mean
    anything. Averaging their *positions* can.

    Equal weights, deliberately. Fitting weights across features is exactly the
    search the trial ledger exists to count, and doing it silently inside a
    strategy would be the worst place to hide it.
    """

    def __init__(
        self,
        features: Sequence[Feature | str],
        *,
        top_n: int = 30,
        min_names: int = 20,
    ) -> None:
        self.features = [BY_NAME[f] if isinstance(f, str) else f for f in features]
        self.top_n = top_n
        self.min_names = min_names
        """How wide the cross-section must be before ranking means anything.

        Defaulted for an equity panel of hundreds. The whole crypto universe is
        20 coins, so the equity default of 50 makes every crypto strategy
        return no positions at all — which reads in a backtest as Sharpe 0.00
        rather than as "this never ran". Sized per universe at the call site.
        """
        names = "+".join(f.name for f in self.features)
        self.name = f"composite({names}, top{top_n})"
        self.lookback = max(f.min_history for f in self.features) + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        symbols = view.symbols()
        rank_sum: dict[str, float] = {}
        counted: dict[str, int] = {}

        for feature in self.features:
            scored: list[tuple[float, str]] = []
            for symbol in symbols:
                value = feature(view.history[symbol])
                if value is not None:
                    scored.append((value, symbol))
            if len(scored) < self.min_names:
                # Too thin a cross-section for this feature to rank. Skipping it
                # is right; ranking 3 names would give them extreme positions on
                # no information.
                continue
            scored.sort()
            for position, (_, symbol) in enumerate(scored):
                rank_sum[symbol] = rank_sum.get(symbol, 0.0) + position / len(scored)
                counted[symbol] = counted.get(symbol, 0) + 1

        # A symbol scored by only some features is not comparable to one scored
        # by all of them, so it is dropped rather than averaged over fewer.
        wanted = len(self.features)
        eligible = [(rank_sum[s] / counted[s], s) for s in rank_sum if counted[s] == wanted]
        if len(eligible) < self.min_names:
            return {}

        eligible.sort(reverse=True)
        chosen = [symbol for _, symbol in eligible[: self.top_n]]
        return normalise(dict.fromkeys(chosen, 1.0 / len(chosen)))


# --- the published set ------------------------------------------------------
#
# Every entry names its paper. `top_n` is 30 throughout and `rebalance` follows
# the paper's own horizon where it states one, so the parameters are the
# literature's rather than ours — anything else is a fitted choice that would
# have to be counted as search.


def momentum_12_1(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Jegadeesh & Titman (1993). Buy 12-month winners, skipping last month.

    The skip is the point: month -1 carries the short-term reversal that
    `reversal_1m` trades in the opposite direction, and without the skip the
    two effects cancel.
    """
    return RankAndHold("momentum_12_1", top_n=top_n, min_names=min_names)


def momentum_6_1(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Jegadeesh & Titman (1993), the shorter formation window they also test."""
    return RankAndHold("momentum_6_1", top_n=top_n, min_names=min_names)


def short_term_reversal(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Jegadeesh (1990), Lehmann (1990). Last month's losers outperform.

    `reversal_1m` is already negated in the library, so ranking it high is
    buying the losers — the sign convention that every feature is oriented so
    higher is better.
    """
    return RankAndHold("reversal_1m", top_n=top_n, min_names=min_names)


def low_volatility(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Baker, Bradley & Wurgler (2011). Low-volatility stocks outperformed.

    The opposite of what risk pricing predicts, over 41 years of US data.
    """
    return RankAndHold("low_volatility", top_n=top_n, min_names=min_names)


def fifty_two_week_high(top_n: int = 30, min_names: int = 50) -> Strategy:
    """George & Hwang (2004). Nearness to the 52-week high forecasts returns.

    Distinct from momentum and, in the paper, dominating it — and unlike
    momentum its forecasts do not reverse over the long run.
    """
    return RankAndHold("price_to_52w_high", top_n=top_n, min_names=min_names)


def illiquidity_premium(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Amihud (2002). Illiquid stocks earn a premium for being illiquid.

    The one on this list most likely to be an artefact *here*: T-907 records
    that market impact is not modelled at all, so a backtest of an illiquidity
    premium is being paid the premium without paying its cost.
    """
    return RankAndHold("illiquidity_amihud", top_n=top_n, min_names=min_names)


def small_size(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Banz (1981). Small firms outearned large ones.

    `small_size` is negated log price, which is a **weak proxy** for market
    capitalisation — the library says so. A low price is not a small company.
    Registered because the effect is real in the literature; the implementation
    is the honest limit of what the panel supports.
    """
    return RankAndHold("small_size", top_n=top_n, min_names=min_names)


def quality_composite(top_n: int = 30, min_names: int = 20) -> Strategy:
    """Low volatility, shallow drawdowns, and liquidity, ranked together.

    Not from one paper. The construction is standard and the components each
    have their own; combining them is the part that is ours, and it is exactly
    the kind of choice that should be counted as search rather than presented
    as a finding.
    """
    return Composite(
        ["low_volatility", "max_drawdown", "turnover_liquidity"], top_n=top_n, min_names=min_names
    )


def momentum_quality(top_n: int = 30, min_names: int = 20) -> Strategy:
    """Momentum, filtered by not-falling-apart.

    Momentum's known failure is the crash: winners are high-beta going into a
    reversal. Averaging its rank with drawdown and volatility is the standard
    response, and whether it helps here is an empirical question nobody has
    asked of this data.
    """
    return Composite(
        ["momentum_12_1", "max_drawdown", "low_volatility"], top_n=top_n, min_names=min_names
    )


def value_reversal(top_n: int = 30, min_names: int = 20) -> Strategy:
    """Short-term reversal combined with liquidity.

    Reversal is strongest in illiquid names and most expensive to trade there,
    which is the tension this pairing exposes rather than resolves.
    """
    return Composite(["reversal_1m", "turnover_liquidity"], top_n=top_n, min_names=min_names)


BUILDERS: dict[str, Callable[..., Strategy]] = {
    "momentum_12_1": momentum_12_1,
    "momentum_6_1": momentum_6_1,
    "short_term_reversal": short_term_reversal,
    "low_volatility": low_volatility,
    "fifty_two_week_high": fifty_two_week_high,
    "illiquidity_premium": illiquidity_premium,
    "small_size": small_size,
    "quality_composite": quality_composite,
    "momentum_quality": momentum_quality,
    "value_reversal": value_reversal,
}
"""Name to builder. The registry and the batch runner both read this, so a
strategy cannot appear in the console without something able to build it."""

# Strategies from papers on Indian equities (`research/papers/`). Kept in their
# own module because each follows its own paper's rules rather than the shared
# `RankAndHold` shape.
from eulerlab.backtest.india_papers import BUILDERS as _INDIA  # noqa: E402

BUILDERS.update(_INDIA)

# Daily rules from public GitHub repositories (research 113).
from eulerlab.backtest.github_daily import BUILDERS as _GITHUB_DAILY  # noqa: E402

BUILDERS.update(_GITHUB_DAILY)

# Momentum and reversal refinements with published evidence (research 113, batch 3).
from eulerlab.backtest.evidence_daily import BUILDERS as _EVIDENCE_DAILY  # noqa: E402

BUILDERS.update(_EVIDENCE_DAILY)

# Earnings-event strategies on NSE's dated announcements (research 113, batch 5).
from eulerlab.backtest.events_daily import BUILDERS as _EVENTS_DAILY  # noqa: E402

BUILDERS.update(_EVENTS_DAILY)
