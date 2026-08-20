"""Monte Carlo resampling: was the result an accident of ordering, or of luck?

Adapted from the `MonteCarloSimulation` module in 2CentsCapital's TradeMaster
(`~/Documents/TradeMaster_Avneesh`), which shuffles price data and re-runs the
backtest. The idea is theirs; the implementation here differs on two points
that matter, and both are worth stating because they change what the number
means.

**It resamples returns, not prices.** TradeMaster shuffles the price series and
re-runs the whole backtest, which costs one backtest per simulation — a
thousand simulations is a thousand backtests. Resampling the realised daily
returns costs nothing and asks a cleaner question, because re-running a
strategy on shuffled prices also changes *which trades it takes*, mixing two
effects together. Here the strategy's decisions are held fixed and only the
arrival order or the sample is disturbed.

**It runs two different tests, because they answer different questions.** This
is the part most implementations get wrong, including by implication any that
report a "Monte Carlo Sharpe distribution" from shuffling alone:

- **`shuffle`** reorders the same returns. Mean and standard deviation are
  unchanged, so **the Sharpe ratio is mathematically identical in every
  path** — reporting a distribution of it would be reporting zero. What
  *does* change is the path: drawdowns depend entirely on the order losses
  arrive in. So shuffling answers **"how bad could the drawdown have been?"**
- **`bootstrap`** samples returns with replacement. That changes the mean and
  the standard deviation, so it gives a genuine confidence interval on the
  Sharpe — it answers **"how precisely do we know this number?"**

Both are seeded, so a repeat run is byte-identical, as `CLAUDE.md` requires.

**What neither can do.** Resampling assumes returns are exchangeable —
independent and identically distributed. Real returns are neither: volatility
clusters, and a crash is a run of bad days rather than bad days sprinkled
evenly. So the shuffled drawdown distribution is, if anything, **optimistic**
about the real worst case, because shuffling breaks up exactly the clustering
that produces the worst drawdowns. Treat the interval as a lower bound on
uncertainty, never as the full picture.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from eulerlab.validation.statistics import sharpe_stats


def _equity_path(returns: Sequence[float], start: float = 1.0) -> list[float]:
    equity, value = [start], start
    for daily in returns:
        value *= 1.0 + daily
        equity.append(value)
    return equity


def max_drawdown(returns: Sequence[float]) -> float:
    """Worst peak-to-trough fall along the path, as a negative fraction."""
    peak, worst = -math.inf, 0.0
    for value in _equity_path(returns):
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile. `fraction` in [0, 1]."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


@dataclass(frozen=True)
class Distribution:
    """A resampled statistic, summarised by the quantiles worth acting on."""

    name: str
    observed: float
    p05: float
    p50: float
    p95: float
    worst: float
    n: int
    unit: str = "ratio"
    """`"fraction"` for anything that is a proportion, `"ratio"` otherwise.

    Every value in this class is stored in its NATURAL unit — a drawdown of
    minus a third is `-0.333`, never `-33.3`. The first version stored
    drawdowns pre-multiplied by 100 for display, which produced two bugs at
    once: `render` applied `:.1%` to an already-scaled number and printed
    -2258.9%, and the shallower/deeper comparison tested a raw fraction against
    a percentage and always took the wrong branch. Formatting is a property of
    the display, so it belongs here and not in the stored value."""

    def _fmt(self, value: float) -> str:
        return f"{value:>8.1%}" if self.unit == "fraction" else f"{value:>8.2f}"

    def line(self) -> str:
        return (
            f"  {self.name:<20} observed {self._fmt(self.observed)}   "
            f"5th {self._fmt(self.p05)}   median {self._fmt(self.p50)}   "
            f"95th {self._fmt(self.p95)}   worst {self._fmt(self.worst)}"
        )


@dataclass
class MonteCarloResult:
    simulations: int
    seed: int
    drawdown: Distribution
    sharpe: Distribution
    observed_sharpe: float
    observed_drawdown: float

    @property
    def drawdown_is_understated(self) -> bool:
        """Was the realised drawdown luckier than the median resampled path?

        The question this whole module exists for. A strategy whose observed
        drawdown sits well above the median of its own reshuffled paths has not
        been tested by history — it simply has not met its bad ordering yet.
        """
        return self.observed_drawdown > self.drawdown.p50

    @property
    def sharpe_could_be_zero(self) -> bool:
        """Does the bootstrap interval include no edge at all?"""
        return self.sharpe.p05 <= 0.0

    def render(self) -> str:
        lines = [
            "",
            f"monte carlo — {self.simulations:,} simulations, seed {self.seed}",
            "",
            "  shuffle: same returns, different order. Sharpe is unchanged by",
            "  construction, so this measures PATH risk only.",
            self.drawdown.line(),
            "",
            "  bootstrap: resampled with replacement. This is the confidence",
            "  interval on the edge itself.",
            self.sharpe.line(),
            "",
        ]
        if self.drawdown_is_understated:
            lines.append(
                f"  The realised drawdown ({self.observed_drawdown:.1%}) is SHALLOWER than the\n"
                f"  median reshuffled path ({self.drawdown.p50:.1%}). History was kind about\n"
                f"  ordering. A 5th-percentile ordering would have lost {abs(self.drawdown.p05):.1%}."
            )
        else:
            lines.append(
                f"  The realised drawdown ({self.observed_drawdown:.1%}) is at or worse than the\n"
                f"  median reshuffled path ({self.drawdown.p50:.1%}), so the backtest already\n"
                f"  saw an unkind ordering."
            )
        if self.sharpe_could_be_zero:
            lines.append(
                f"\n  The 5th percentile of the bootstrapped Sharpe is {self.sharpe.p05:.2f}, which is\n"
                f"  at or below zero. The data cannot rule out that there is no edge."
            )
        lines.append(
            "\n  Both tests assume returns are exchangeable. Real returns cluster, and\n"
            "  shuffling breaks up exactly the clustering that causes the worst\n"
            "  drawdowns — so treat this as a LOWER bound on the risk, not the whole of it."
        )
        return "\n".join(lines)


def run(
    returns: Sequence[float],
    *,
    simulations: int = 1000,
    seed: int = 20260820,
    periods_per_year: int = 252,
) -> MonteCarloResult:
    """Resample `returns` two ways and summarise both.

    Seeded, so the same returns always give the same answer. An unseeded Monte
    Carlo would make every re-run of the validation battery disagree slightly
    with the last, which is indistinguishable from a real change.
    """
    if len(returns) < 30:
        msg = f"{len(returns)} returns is too few to resample meaningfully"
        raise ValueError(msg)

    rng = random.Random(seed)
    observed_sharpe = sharpe_stats(returns, periods_per_year=periods_per_year).sharpe
    observed_drawdown = max_drawdown(returns)

    pool = list(returns)
    drawdowns: list[float] = []
    sharpes: list[float] = []
    for _ in range(simulations):
        shuffled = pool[:]
        rng.shuffle(shuffled)
        drawdowns.append(max_drawdown(shuffled))

        sampled = [pool[rng.randrange(len(pool))] for _ in range(len(pool))]
        sharpes.append(sharpe_stats(sampled, periods_per_year=periods_per_year).sharpe)

    drawdowns.sort()
    sharpes.sort()

    return MonteCarloResult(
        simulations=simulations,
        seed=seed,
        observed_sharpe=observed_sharpe,
        observed_drawdown=observed_drawdown,
        drawdown=Distribution(
            "max drawdown",
            observed=observed_drawdown,
            p05=_percentile(drawdowns, 0.05),
            p50=_percentile(drawdowns, 0.50),
            p95=_percentile(drawdowns, 0.95),
            worst=drawdowns[0],
            n=simulations,
            unit="fraction",
        ),
        sharpe=Distribution(
            "sharpe",
            observed=observed_sharpe,
            p05=_percentile(sharpes, 0.05),
            p50=_percentile(sharpes, 0.50),
            p95=_percentile(sharpes, 0.95),
            worst=sharpes[0],
            n=simulations,
        ),
    )
