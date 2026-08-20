"""What searching costs: the bar rises for everything, every time you look.

This module exists because the research loop is the dangerous part of the
project. `docs/AI_BUILD_PLAN.md` puts it plainly: *an AI that can generate 100
strategies a month against a leaky validation process is a machine for losing
money efficiently.* The validation process is no longer leaky — Sprints 13 and
14 saw to that — but the arithmetic underneath it is easy to forget, and it is
brutal.

**Every hypothesis evaluated raises the bar for all of them.** The Deflated
Sharpe correction divides by how many things were tried, so trying more makes
each one harder to justify. That is not a penalty bolted on; it is what the
statistic means. The best of twenty coin-flip strategies looks good precisely
*because* twenty were tried.

The numbers, from `expected_max_sharpe`:

| hypotheses tried | best Sharpe pure noise would produce |
|---|---|
| 1 | 0.00 |
| 10 | 1.57 |
| 20 | 1.87 |
| 50 | 2.25 |
| 100 | 2.53 |

A real strategy must beat that, not zero. At twenty trials a Sharpe of 1.8 is
*worse than nothing* — it is below what searching that hard produces from
noise alone.

So this module is deliberately discouraging. It is called before generating
hypotheses, not after, and it answers: given what we have already spent, what
would this search cost, and what would a candidate then have to achieve?

**The trial counter includes hypotheses that were generated and never
tested.** That is intentional and it is the part people argue with. If ten
cards are written and only the most promising three are validated, the
selection already happened — the discarded seven informed the choice, and
pretending otherwise understates the search in the direction that flatters.
"""

from __future__ import annotations

from dataclasses import dataclass

from eulerlab.validation.ledger import count as ledger_count
from eulerlab.validation.statistics import expected_max_sharpe, min_backtest_length


@dataclass(frozen=True)
class SearchCost:
    """What a search would cost, before it is run."""

    trials_already: int
    trials_proposed: int
    available_years: float

    @property
    def trials_after(self) -> int:
        return self.trials_already + self.trials_proposed

    @property
    def bar_now(self) -> float:
        """Sharpe that pure noise would be expected to produce today."""
        return expected_max_sharpe(max(self.trials_already, 1))

    @property
    def bar_after(self) -> float:
        return expected_max_sharpe(max(self.trials_after, 1))

    @property
    def years_needed_after(self) -> float:
        """History required to distinguish a Sharpe of 1.0 from luck afterwards."""
        return min_backtest_length(max(self.trials_after, 1), target_sharpe=1.0)

    @property
    def affordable(self) -> bool:
        """Whether the history we hold could still support a claim afterwards.

        Not a judgement about whether the ideas are good. Purely: after this
        search, would there be enough history left to distinguish a decent
        strategy from the best of the noise? If not, the search cannot produce
        a defensible result no matter what it finds.
        """
        return self.years_needed_after <= self.available_years

    def render(self) -> str:
        lines = [
            "",
            "-- what this search costs --",
            f"  hypotheses already evaluated : {self.trials_already}",
            f"  proposed now                 : {self.trials_proposed}",
            f"  total afterwards             : {self.trials_after}",
            "",
            f"  a candidate must beat        : Sharpe {self.bar_now:.2f}  (today)",
            f"                                 Sharpe {self.bar_after:.2f}  (after this search)",
            f"  history needed at SR 1.0     : {self.years_needed_after:.1f} years",
            f"  history available            : {self.available_years:.1f} years",
        ]
        if not self.affordable:
            lines.append(
                "\n  THIS SEARCH IS NOT AFFORDABLE. Afterwards, no strategy this data\n"
                "  can support would clear the bar the search itself created. Generating\n"
                "  the hypotheses would make every existing candidate harder to justify\n"
                "  and could not produce a defensible new one."
            )
        elif self.bar_after > self.bar_now * 1.25:
            lines.append(
                f"\n  This raises the bar by {(self.bar_after / max(self.bar_now, 0.01) - 1):.0%} for every\n"
                "  candidate, including ones already evaluated. Generate fewer, better\n"
                "  hypotheses rather than more."
            )
        return "\n".join(lines)


def price_search(n_proposed: int, *, available_years: float) -> SearchCost:
    """Cost a proposed search against the real trial ledger."""
    return SearchCost(
        trials_already=ledger_count(),
        trials_proposed=max(n_proposed, 0),
        available_years=available_years,
    )
