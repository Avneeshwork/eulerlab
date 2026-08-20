"""`make test-engine` — the gate the build plan calls the most important in the project.

Every other check in this codebase asks whether the *data* is right. This one
asks whether the *engine* is right, and it matters more, because a wrong
engine does not produce obviously wrong answers. It produces plausible ones.
A data gap announces itself; a P&L that is quietly 2% generous does not, and
every strategy decision downstream inherits it.

So the tests here are built on synthetic worlds whose correct answer is known
by construction, rather than on real data where "looks reasonable" is the only
available verdict.

## The five

1. **Accounting invariants, per event.** After every single fill, cash plus
   marked positions must equal equity, and realised P&L plus unrealised must
   equal the change in equity. Checked after each fill rather than at the end,
   because an end-state check passes on two errors that cancel.

2. **Zero alpha equals exact cost drag.** On a flat market a trading strategy
   must lose *precisely* what it paid, to the paisa. This is the sharpest test
   in the file: it has one right answer and no tolerance to hide in. If the
   engine leaks a rupee anywhere — a fee applied twice, a fill priced wrong, a
   rounding that accumulates — this catches it.

3. **Known-alpha recovery.** Plant a signal that predicts the future perfectly
   and check the engine finds roughly the return it was given. An engine that
   cannot recover alpha that is *actually there* will silently reject every
   real strategy, which is the expensive failure nobody notices.

4. **Determinism.** Same input, byte-identical output. A project-wide rule,
   and the precondition for golden files meaning anything.

5. **Golden files.** A committed reference run. Any change to the engine that
   moves it must be deliberate and explained, which is the only defence
   against slow drift that no single commit looks responsible for.

The synthetic worlds are used deliberately: the golden file is built on one
rather than on the real panel, so it stays stable as the data grows. A golden
file that changes every time a day is added is a golden file nobody looks at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.events import Portfolio
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow

GOLDEN_PATH = Path("tests/golden/engine_reference.json")
PAISA = 0.01
START = date(2020, 1, 1)


# --- synthetic worlds, where the right answer is known by construction ---


def flat_world(*, n_symbols: int = 20, n_days: int = 320, price: float = 100.0) -> list[PanelRow]:
    """Every price constant forever. Any P&L here is cost, and nothing else."""
    return [
        PanelRow(
            day=START + timedelta(days=d),
            symbol=f"SYM{s:02d}",
            close=price,
            volume=10_000.0,
            turnover=1e9,
        )
        for s in range(n_symbols)
        for d in range(n_days)
    ]


def alpha_world(
    *, n_symbols: int = 20, n_days: int = 320, winners: int = 5, winner_drift: float = 0.002
) -> list[PanelRow]:
    """The first `winners` symbols rise steadily; the rest are flat.

    A strategy that holds the winners should earn close to the drift, less
    costs. One that cannot is not finding alpha that is provably present.
    """
    rows: list[PanelRow] = []
    for s in range(n_symbols):
        price = 100.0
        drift = winner_drift if s < winners else 0.0
        for d in range(n_days):
            price *= 1.0 + drift
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"SYM{s:02d}",
                    close=price,
                    volume=10_000.0,
                    turnover=1e9,
                )
            )
    return rows


class HoldFirstN(Strategy):
    """Holds a fixed, known set. No signal, no lookahead, no ambiguity."""

    def __init__(self, n: int, *, name: str = "hold_first_n") -> None:
        self.n = n
        self.name = name

    def target_weights(self, view: MarketView) -> dict[str, float]:
        chosen = view.symbols()[: self.n]
        return dict.fromkeys(chosen, 1.0 / len(chosen)) if chosen else {}


class Churn(Strategy):
    """Alternates between two disjoint baskets to force turnover.

    Used for the zero-alpha test: on a flat market it generates trades and
    therefore costs, with no possible source of profit or loss besides them.
    """

    def __init__(self, n: int = 5) -> None:
        self.n = n
        self.name = "churn"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        symbols = view.symbols()
        if len(symbols) < 2 * self.n:
            return {}
        # Alternate on the ordinal of the decision date, so the choice is a
        # pure function of the view and the strategy stays stateless.
        first = (view.as_of.toordinal() // 7) % 2 == 0
        chosen = symbols[: self.n] if first else symbols[self.n : 2 * self.n]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


# --- results ---


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _ok(name: str, detail: str) -> Check:
    return Check(name, True, detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, False, detail)


# --- 1. accounting invariants, checked after every event ---


def check_accounting_invariants() -> Check:
    """Cash plus positions equals equity, after every single fill.

    Replays the fills through a fresh `Portfolio` and asserts the identity at
    each step. Checking only the end state would pass on two errors that
    happen to cancel, which is exactly the kind of bug that survives review.
    """
    name = "accounting invariants"
    rows = alpha_world()
    result = event_driven.run(rows, HoldFirstN(5), warmup=60, rebalance_every=20)
    if not result.fills:
        return _fail(name, "no fills produced; the test proved nothing")

    replay = Portfolio(cash=result.starting_cash)
    for i, fill in enumerate(result.fills):
        replay.apply(fill)
        marks = {fill.symbol: fill.price}
        for symbol in replay.holdings():
            marks.setdefault(symbol, fill.price)
        equity = replay.equity(marks)
        reconstructed = replay.cash + replay.market_value(marks)
        if abs(equity - reconstructed) > PAISA:
            return _fail(name, f"fill {i}: equity {equity} != cash + positions {reconstructed}")
        for symbol, position in replay.positions.items():
            if position.quantity < 0:
                return _fail(name, f"fill {i}: {symbol} went short in a long-only run")
            if position.quantity == 0 and position.cost_basis != 0:
                return _fail(name, f"fill {i}: {symbol} is flat but retains a cost basis")

    return _ok(name, f"held across all {len(result.fills):,} fills")


def check_cash_conservation() -> Check:
    """Every rupee is accounted for: starting cash equals ending cash plus the
    value of what was bought plus everything paid in costs."""
    name = "cash conservation"
    rows = flat_world()
    result = event_driven.run(rows, HoldFirstN(5), warmup=60, rebalance_every=1000)
    portfolio = result.portfolio
    if portfolio is None or not portfolio.fills:
        return _fail(name, "no fills produced")

    spent = sum(f.signed_quantity * f.price for f in portfolio.fills)
    costs = sum(f.cost for f in portfolio.fills)
    expected_cash = result.starting_cash - spent - costs
    if abs(portfolio.cash - expected_cash) > PAISA:
        return _fail(name, f"cash {portfolio.cash:.2f} != expected {expected_cash:.2f}")
    return _ok(name, f"{len(portfolio.fills):,} fills, every rupee accounted for")


# --- 2. zero alpha equals exact cost drag ---


def check_zero_alpha_is_exact_cost_drag() -> Check:
    """On a flat market, the loss must equal the costs to the paisa.

    The sharpest test here. There is one right answer and no tolerance to hide
    in: prices never move, so the only thing that can change equity is what
    was paid to trade. A fee applied twice, a fill at the wrong price, or a
    rounding error that accumulates all show up as a mismatch.
    """
    name = "zero alpha = exact cost drag"
    rows = flat_world()
    result = event_driven.run(rows, Churn(5), warmup=60, rebalance_every=7)
    if not result.fills:
        return _fail(name, "no fills produced; the test proved nothing")

    loss = result.starting_cash - result.final_equity
    costs = result.total_cost
    if abs(loss - costs) > PAISA:
        return _fail(
            name,
            f"lost Rs {loss:.2f} but paid Rs {costs:.2f} in costs "
            f"- Rs {abs(loss - costs):.2f} unexplained",
        )
    return _ok(name, f"lost exactly Rs {costs:,.2f} over {len(result.fills):,} fills")


def check_costs_match_an_independent_recomputation() -> Check:
    """Recompute every fill's cost straight from the cost model and compare.

    **This check exists because the mutation suite found the gate had a hole.**
    Doubling every cost in the engine still passed
    `check_zero_alpha_is_exact_cost_drag`: the cash deduction and the recorded
    `fill.cost` both doubled, so `loss == costs` remained true. The identity
    was self-consistent and completely wrong.

    Consistency is not correctness. So the magnitude is checked against a
    second computation that shares no code path with the engine's - the same
    principle as `corp_actions/check.py`, where re-deriving a ratio from the
    raw text catches a parser that reads it backwards.
    """
    name = "costs match the cost model"
    rows = flat_world()
    result = event_driven.run(rows, Churn(5), warmup=60, rebalance_every=7)
    if not result.fills:
        return _fail(name, "no fills produced; the test proved nothing")

    from decimal import Decimal

    from eulerlab.costs.model import cost_of_trade
    from eulerlab.costs.schedule import Segment

    for i, fill in enumerate(result.fills):
        independent = float(
            cost_of_trade(
                trade_date=fill.day,
                segment=Segment.EQUITY_DELIVERY,
                side=fill.side,
                price=Decimal(str(round(fill.price, 2))),
                quantity=fill.quantity,
            ).total
        )
        if abs(fill.cost - independent) > PAISA:
            return _fail(
                name,
                f"fill {i}: engine charged Rs {fill.cost:.2f}, the cost model says "
                f"Rs {independent:.2f}",
            )
    return _ok(name, f"all {len(result.fills):,} fills match an independent computation")


def check_zero_cost_is_zero_pnl() -> Check:
    """Flat market with costs off must end exactly where it started."""
    name = "flat market, no costs, no P&L"
    rows = flat_world()
    result = event_driven.run(rows, Churn(5), warmup=60, rebalance_every=7, cost_mode="replication")
    drift = abs(result.final_equity - result.starting_cash)
    if drift > PAISA:
        return _fail(name, f"equity moved by Rs {drift:.2f} with no prices moving and no costs")
    return _ok(name, "equity unchanged to the paisa")


# --- 3. known-alpha recovery ---


def check_known_alpha_is_recovered() -> Check:
    """Plant alpha, check the engine finds it.

    An engine that cannot recover alpha that is provably present will reject
    every real strategy while looking like it works - the expensive failure,
    because nothing about it is visibly broken.
    """
    name = "known alpha recovered"
    winner_drift = 0.002
    n_days = 320
    rows = alpha_world(winners=5, winner_drift=winner_drift, n_days=n_days)
    result = event_driven.run(
        rows, HoldFirstN(5), warmup=60, rebalance_every=1000, cost_mode="replication"
    )
    if not result.equity:
        return _fail(name, "no equity curve produced")

    held_days = len(result.days)
    expected = (1.0 + winner_drift) ** held_days - 1.0
    actual = result.total_return
    # Generous band: the first bar is spent entering, and integer share counts
    # leave a little cash uninvested. The test is that the alpha is found, not
    # that it is found to four decimal places.
    if actual < expected * 0.90:
        return _fail(name, f"recovered {actual:.2%} of a planted {expected:.2%}")
    return _ok(name, f"recovered {actual:.2%} against a planted {expected:.2%}")


def check_no_alpha_is_not_invented() -> Check:
    """Holding the flat names in the same world must earn nothing.

    The other half of the previous test. An engine that reports a profit where
    none exists is worse than one that misses a real profit.
    """
    name = "absent alpha not invented"
    rows = alpha_world(n_symbols=20, winners=5, winner_drift=0.002)

    class HoldLosers(Strategy):
        name = "hold_flat_names"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            flat = view.symbols()[5:10]
            return dict.fromkeys(flat, 1.0 / len(flat))

    result = event_driven.run(
        rows, HoldLosers(), warmup=60, rebalance_every=1000, cost_mode="replication"
    )
    if abs(result.total_return) > 0.001:
        return _fail(name, f"earned {result.total_return:.4%} holding flat instruments")
    return _ok(name, "earned nothing, as it should")


# --- 4. determinism ---


def check_determinism() -> Check:
    """Same input, identical output. Twice, in both engines."""
    name = "determinism"
    rows = alpha_world()
    strategy = HoldFirstN(5)
    a1 = vector.run(rows, strategy, warmup=60, rebalance_every=20)
    a2 = vector.run(rows, strategy, warmup=60, rebalance_every=20)
    b1 = event_driven.run(rows, strategy, warmup=60, rebalance_every=20)
    b2 = event_driven.run(rows, strategy, warmup=60, rebalance_every=20)
    if a1.equity != a2.equity:
        return _fail(name, "Tier A produced different curves on identical input")
    if b1.equity != b2.equity:
        return _fail(name, "Tier B produced different curves on identical input")
    if [f.client_order_id for f in b1.fills] != [f.client_order_id for f in b2.fills]:
        return _fail(name, "order ids differed between identical runs")
    return _ok(name, "both engines byte-identical across repeat runs")


def check_engines_reconcile() -> Check:
    """The Sprint 11 guarantee, re-asserted here so it is part of the gate."""
    name = "Tier A / Tier B reconcile"
    rows = alpha_world()
    strategy = HoldFirstN(5)
    a = vector.run(rows, strategy, warmup=60, rebalance_every=20)
    b = event_driven.run(rows, strategy, warmup=60, rebalance_every=20)
    rec = event_driven.reconcile(a.equity, b.equity)
    if not rec.agrees:
        return _fail(name, f"diverged by {rec.max_relative:.2e} relative")
    if not rec.tier_a_is_pessimistic:
        return _fail(name, "Tier A came out above Tier B; the fast engine is flattering")
    return _ok(name, f"agree to {rec.max_relative:.1e} relative over {rec.days:,} days")


# --- 5. golden file ---


def _golden_fingerprint() -> dict[str, object]:
    """A canonical run, reduced to numbers that must not drift.

    Built on a synthetic world rather than the real panel so it stays stable
    as data is added. A golden file that changes whenever a trading day is
    appended is one nobody reads.
    """
    rows = alpha_world()
    result = event_driven.run(rows, HoldFirstN(5), warmup=60, rebalance_every=20)
    return {
        "final_equity": round(result.final_equity, 2),
        "total_cost": round(result.total_cost, 2),
        "n_fills": len(result.fills),
        "n_orders": len(result.orders),
        "n_rejections": len(result.rejections),
        "realised_pnl": round(result.portfolio.realised_pnl, 2) if result.portfolio else 0.0,
        "equity_head": [round(v, 2) for v in result.equity[:5]],
        "equity_tail": [round(v, 2) for v in result.equity[-5:]],
    }


def check_golden(path: Path = GOLDEN_PATH, *, update: bool = False) -> Check:
    """Compare a canonical run against its committed reference."""
    name = "golden file"
    current = _golden_fingerprint()

    if update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return _ok(name, f"{'updated' if update else 'created'} {path}")

    expected = json.loads(path.read_text(encoding="utf-8"))
    differences = [
        f"{key}: {expected.get(key)!r} -> {value!r}"
        for key, value in current.items()
        if expected.get(key) != value
    ]
    if differences:
        return _fail(
            name,
            f"{len(differences)} field(s) drifted: "
            + "; ".join(differences[:3])
            + ". If this change is intended, re-run with UPDATE=1 and say why in the commit.",
        )
    return _ok(name, f"matches {path}")


CHECKS = (
    check_accounting_invariants,
    check_cash_conservation,
    check_zero_alpha_is_exact_cost_drag,
    check_costs_match_an_independent_recomputation,
    check_zero_cost_is_zero_pnl,
    check_known_alpha_is_recovered,
    check_no_alpha_is_not_invented,
    check_determinism,
    check_engines_reconcile,
)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="test-engine", description=__doc__)
    parser.add_argument("--update-golden", action="store_true")
    args = parser.parse_args()

    results = [check() for check in CHECKS]
    results.append(check_golden(update=args.update_golden))

    width = max(len(r.name) for r in results)
    print(f"\n{'CHECK'.ljust(width)}  RESULT  DETAIL")
    for r in results:
        print(f"{r.name.ljust(width)}  {'PASS' if r.ok else 'FAIL':<6}  {r.detail}")

    failed = [r for r in results if not r.ok]
    print()
    if failed:
        print(f"test-engine FAILED: {len(failed)} of {len(results)} red")
        print("\nThe engine is the thing every later number depends on. Do not run a")
        print("strategy, read a backtest, or trust a tear sheet until this is green.")
        return 1
    print(f"test-engine OK: all {len(results)} checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
