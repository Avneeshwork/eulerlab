"""The reality gap: why did paper not do what the backtest said it would?

The build plan asks for a daily attribution report with residual under 10%.
This is that report, and the first thing to say about it is what the residual
actually means here, because the honest answer is less impressive than the
number looks.

**The decomposition is an identity, not a model.** Both books are ours. We
have every fill on both sides, so the difference in final equity can be split
into its causes exactly, and the residual comes out at zero to the paisa. A
residual under 10% is not evidence that we understand execution — it is
evidence that the arithmetic closes. It would be dishonest to present it as
the former, and the residual is checked against **0.01 rupees**, not 10%,
precisely so that the check is one that can actually fail.

The number the build plan really wants — how much of a *live* shortfall we can
explain — needs a real broker on the other side, and cannot exist before
Sprint 29. What this gives instead is the machinery, verified against a case
where the true answer is known.

**The frictionless run is the real test.** Set slippage to zero and reject
nothing, and paper and backtest must produce *byte-identical* equity. They
share one loop, one strategy, one sizing path, one cost model, so any
difference at all is a defect in the order path rather than a fact about
markets. That check is worth more than the decomposition: it is the one that
catches the drift `CLAUDE.md` warns about.

The five components, and what each means:

| component | cause |
|---|---|
| slippage on matched trades | same trade, different price |
| cost charged on a different price | one cost model, applied to two different fills |
| trades the backtest made and paper did not | rejections, kill switch, unresolved orders |
| trades paper made and the backtest did not | path divergence — see below |
| position divergence, marked | the two books ended holding different things |

Two of those need a caveat, because the obvious reading of each is wrong.

**"Trades paper made and the backtest did not" is not an error term.** The
first instinct is that it should be zero and anything else means the order
path invented a trade. That is only true in the frictionless case. As soon as
one fill differs by a rupee, the two books hold different cash, so the next
rebalance sizes every position slightly differently, and from then on they
trade different quantities on different days. Path divergence compounds from
the first difference; it is a consequence of slippage, not a separate defect.

**"Cost charged on a different price" is not cost-model error.** Both books
price their fills with the same model — there is only one — so this line is
that single model applied to two different fill prices. The number that would
measure model error is the model against a real contract note, which is T-906
and needs the operator.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from eulerlab.backtest import event_driven
from eulerlab.backtest.events import Fill
from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.costs.schedule import Side
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, read_panel
from eulerlab.oms.paper_broker import PaperFaults
from eulerlab.paper import runner

CLOSES_TO = 0.01
"""One paisa. The decomposition is exact, so anything above this is a bug in
the decomposition, not a subtlety about markets."""


def _signed(fill: Fill) -> int:
    return fill.quantity if fill.side is Side.BUY else -fill.quantity


@dataclass(frozen=True)
class Component:
    name: str
    rupees: float
    why: str

    def line(self) -> str:
        return f"  {self.name:<44} {self.rupees:>14,.2f}   {self.why}"


@dataclass
class Attribution:
    backtest_equity: float
    paper_equity: float
    components: list[Component] = field(default_factory=list)
    trades_matched: int = 0
    trades_backtest_only: int = 0
    trades_paper_only: int = 0

    @property
    def gap(self) -> float:
        """Negative means paper did worse, which is the expected direction."""
        return self.paper_equity - self.backtest_equity

    @property
    def explained(self) -> float:
        return sum(c.rupees for c in self.components)

    @property
    def residual(self) -> float:
        return self.gap - self.explained

    @property
    def closes(self) -> bool:
        return abs(self.residual) <= CLOSES_TO

    @property
    def residual_fraction(self) -> float:
        return abs(self.residual) / abs(self.gap) if self.gap else 0.0

    def render(self) -> str:
        lines = [
            "",
            "reality gap — paper against the backtest that authorised it",
            "",
            f"  backtest final equity                        {self.backtest_equity:>14,.2f}",
            f"  paper final equity                           {self.paper_equity:>14,.2f}",
            f"  {'gap':<44} {self.gap:>14,.2f}",
            "",
            f"  {'trades matched':<44} {self.trades_matched:>14,}",
            f"  {'trades the backtest made, paper did not':<44} {self.trades_backtest_only:>14,}",
            f"  {'trades paper made, the backtest did not':<44} {self.trades_paper_only:>14,}",
            "",
            "  attribution",
        ]
        lines.extend(c.line() for c in self.components)
        lines.append("")
        lines.append(f"  {'explained':<44} {self.explained:>14,.2f}")
        lines.append(f"  {'residual':<44} {self.residual:>14,.2f}")
        lines.append("")
        if self.gap == 0.0:
            lines.append(
                "  The gap is EXACTLY zero. Paper and backtest share one loop, one\n"
                "  strategy and one cost path, so with a frictionless broker they must\n"
                "  agree to the last paisa. This is the check that catches the two\n"
                "  systems drifting apart."
            )
        elif self.closes:
            lines.append(
                f"  The decomposition closes to {abs(self.residual):.4f} rupees.\n"
                "  Note what that does and does not show: both books are ours, so the\n"
                "  split is an identity and the residual SHOULD be zero. It proves the\n"
                "  arithmetic, not that live execution is understood."
            )
        else:
            lines.append(
                f"  DOES NOT CLOSE. {self.residual:,.2f} rupees are unexplained, which\n"
                "  means the decomposition is missing a term — not that the market did\n"
                "  something interesting."
            )
        return "\n".join(lines)


def _by_trade(fills: Sequence[Fill]) -> dict[tuple[date, str], Fill]:
    return {(fill.day, fill.symbol): fill for fill in fills}


def _final_marks(
    rows: Sequence[PanelRow], index: dict[str, dict[date, float]], last_day: date
) -> dict[str, float]:
    """Last known price at or before the final day, per symbol.

    Same rule the engine marks with: a holding that did not print on the last
    day is worth roughly yesterday's price, not nothing. Using a different rule
    here would put a difference into the attribution that neither book has.
    """
    marks: dict[str, float] = {}
    for symbol, series in index.items():
        days = sorted(d for d in series if d <= last_day)
        if days:
            marks[symbol] = series[days[-1]]
    return marks


def attribute(
    backtest: event_driven.TierBResult,
    paper: event_driven.TierBResult,
    *,
    marks: dict[str, float],
) -> Attribution:
    """Split the difference in final equity into its causes. Exactly."""
    result = Attribution(backtest_equity=backtest.final_equity, paper_equity=paper.final_equity)
    bt = _by_trade(backtest.fills)
    pp = _by_trade(paper.fills)

    slippage = 0.0
    cost_difference = 0.0
    only_backtest = 0.0
    only_paper = 0.0

    for key in sorted(bt.keys() | pp.keys()):
        b = bt.get(key)
        p = pp.get(key)
        if b is not None and p is not None:
            result.trades_matched += 1
            shared = min(b.quantity, p.quantity)
            sign = 1 if b.side is Side.BUY else -1
            # Paying more on a buy, or receiving less on a sell, both reduce
            # cash. One expression covers both because the sign carries it.
            slippage += -sign * shared * (p.price - b.price)
            cost_difference += -(p.cost - b.cost)
            if b.quantity != p.quantity:
                # The unmatched remainder is a trade one book made and the
                # other did not, so it belongs in those buckets, not here.
                extra_b = b.quantity - shared
                extra_p = p.quantity - shared
                only_backtest += extra_b * sign * b.price
                only_paper += -extra_p * sign * p.price
        elif b is not None:
            result.trades_backtest_only += 1
            # Paper never made this trade, so paper's cash is higher by what
            # the backtest spent (or lower by what it received) and paper does
            # not hold the resulting shares. The share side lands in the
            # position-divergence term below.
            only_backtest += _signed(b) * b.price + b.cost
        else:
            assert p is not None
            result.trades_paper_only += 1
            only_paper += -(_signed(p) * p.price + p.cost)

    bt_holdings = backtest.portfolio.holdings() if backtest.portfolio else {}
    pp_holdings = paper.portfolio.holdings() if paper.portfolio else {}
    divergence = 0.0
    for symbol in sorted(set(bt_holdings) | set(pp_holdings)):
        delta = pp_holdings.get(symbol, 0) - bt_holdings.get(symbol, 0)
        if delta and symbol in marks:
            divergence += delta * marks[symbol]

    result.components = [
        Component(
            "slippage on matched trades",
            slippage,
            "same trade, different price",
        ),
        Component(
            "cost charged on a different price",
            cost_difference,
            "same model, different fill price — not model error (T-906)",
        ),
        Component(
            "trades the backtest made, paper did not",
            only_backtest,
            "cash the backtest spent and paper kept",
        ),
        Component(
            "trades paper made, the backtest did not",
            only_paper,
            "path divergence: once cash differs, sizing differs",
        ),
        Component(
            "position divergence, marked to market",
            divergence,
            "the two books ended holding different things",
        ),
    ]
    return result


def compare(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    root: Path,
    slippage_bps: float = 0.0,
    reject_symbols: set[str] | None = None,
    faults: PaperFaults | None = None,
    rebalance: int = 21,
    warmup: int = 253,
) -> Attribution:
    """Run both books over the same data and decompose the difference.

    The same `rows`, the same `strategy` object, and the same pre-built
    adjusted index — so nothing except the executor can differ.
    """
    index = build_adjusted_index(rows)
    backtest = event_driven.run(
        rows,
        strategy,
        rebalance_every=rebalance,
        warmup=warmup,
        adjusted_index=index,
        asset_class="equity",
    )

    for name in ("orders.jsonl", "paper_broker.json", "KILL_SWITCH"):
        (root / name).unlink(missing_ok=True)
    injected = faults or PaperFaults()
    injected.reject_symbols |= set(reject_symbols or ())
    oms = runner.fresh_oms(root, slippage_bps=slippage_bps, faults=injected)
    paper = runner.run(
        rows,
        strategy,
        oms=oms,
        rebalance=rebalance,
        warmup=warmup,
        adjusted_index=index,
    )

    last_day = backtest.days[-1] if backtest.days else max(r.day for r in rows)
    return attribute(backtest, paper.result, marks=_final_marks(rows, index, last_day))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reality-gap attribution: paper vs backtest.")
    parser.add_argument("--feature", default="momentum_12_1")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--rebalance", type=int, default=21)
    parser.add_argument("--slippage-bps", type=float, default=25.0)
    parser.add_argument("--days", type=int, default=0, help="use only the last N trading days")
    parser.add_argument(
        "--frictionless",
        action="store_true",
        help="zero slippage, nothing rejected: the two must agree exactly",
    )
    args = parser.parse_args(argv)

    if args.feature not in BY_NAME:
        print(f"unknown feature {args.feature!r}; try one of {sorted(BY_NAME)}")
        return 2
    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    if args.days:
        cutoff = sorted({r.day for r in rows})[-args.days :][0]
        rows = [r for r in rows if r.day >= cutoff]

    strategy = RankAndHold(BY_NAME[args.feature], top_n=args.top_n)
    slippage = 0.0 if args.frictionless else args.slippage_bps
    result = compare(
        rows,
        strategy,
        root=runner.PAPER_DIR / "attribution",
        slippage_bps=slippage,
        rebalance=args.rebalance,
    )
    print(f"\nstrategy: {strategy.describe()}   slippage: {slippage:g} bps")
    print(result.render())

    if args.frictionless and result.gap != 0.0:
        print("\nFAILED: a frictionless paper run must reproduce the backtest exactly.")
        return 1
    return 0 if result.closes else 1


if __name__ == "__main__":
    raise SystemExit(main())
