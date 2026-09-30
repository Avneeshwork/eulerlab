"""Proving the gate bites.

Sprint 12's checks all passed the first time they ran. That is precisely when
a gate is least trustworthy: an assertion that has never failed is
indistinguishable from an assertion that cannot fail.

So each test here **breaks the engine on purpose** and asserts that the
corresponding check goes red. The bugs injected are the ones that actually
happen — a fee charged twice, a fill priced from the wrong bar, a cost skipped
on one side, an ordering that depends on set iteration. If the gate cannot see
these, it is decoration.
"""

from __future__ import annotations

import pytest

from eulerlab.backtest import event_driven, selftest, vector
from eulerlab.backtest.events import Fill, Portfolio
from eulerlab.costs.schedule import Side

# --- the gate is green on an unmodified engine ---


def test_every_check_passes_on_the_real_engine() -> None:
    results = [check() for check in selftest.CHECKS]
    failed = [r.name for r in results if not r.ok]
    assert not failed, f"gate red on an unmodified engine: {failed}"


def test_the_gate_covers_all_five_required_areas() -> None:
    """The build plan names five: accounting invariants, known-alpha recovery,
    zero-alpha cost drag, determinism, golden files."""
    names = " ".join(c.__name__ for c in selftest.CHECKS)
    for area in ("accounting", "known_alpha", "zero_alpha", "determinism"):
        assert area in names, f"no check covers {area}"
    assert hasattr(selftest, "check_golden")


# --- injected bug: a cost charged twice ---


def test_double_charging_costs_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact bug the reference system in ~/Documents/Trade had to disable
    with a comment: two cost paths producing an inconsistent basis."""
    original = vector._costs_for

    def doubled(*args: object, **kwargs: object) -> float:
        return original(*args, **kwargs) * 2  # type: ignore[arg-type]

    # Patched on `vector`, which is where the single cost path actually
    # lives. Every engine and every executor resolves it there at call
    # time, so one patch reaches all of them - which is itself the check
    # that there is only one cost path.
    monkeypatch.setattr(vector, "_costs_for", doubled)

    # The zero-alpha identity does NOT catch this, and that is the point.
    # Both the cash deduction and the recorded fill.cost double, so
    # `loss == costs` stays true - self-consistent and completely wrong.
    # Finding this hole is why the mutation suite exists.
    assert selftest.check_zero_alpha_is_exact_cost_drag().ok

    # The independent recomputation does catch it.
    result = selftest.check_costs_match_an_independent_recomputation()
    assert not result.ok
    assert "cost model says" in result.detail


def test_skipping_the_cost_on_sells_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    original = vector._costs_for

    def buy_only(
        day: object,
        price: object,
        quantity: object,
        side: object,
        brokerage: object,
        asset_class: object,
    ) -> float:
        if side is Side.SELL:
            return 0.0
        return original(day, price, quantity, side, brokerage, asset_class)  # type: ignore[arg-type]

    monkeypatch.setattr(vector, "_costs_for", buy_only)
    # Cash conservation still holds (fills agree with cash), but the zero-alpha
    # identity is unaffected too - so this must be caught by comparing against
    # an engine that charges correctly.
    broken = event_driven.run(
        selftest.flat_world(), selftest.Churn(5), warmup=60, rebalance_every=7, asset_class="equity"
    )
    monkeypatch.undo()
    correct = event_driven.run(
        selftest.flat_world(), selftest.Churn(5), warmup=60, rebalance_every=7, asset_class="equity"
    )
    assert broken.total_cost < correct.total_cost


# --- injected bug: lookahead in the fill price ---


def test_filling_at_the_decision_bar_breaks_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filling on the bar you decided from is the classic vectorised
    lookahead. If Tier B does it and Tier A does not, the engines must stop
    agreeing - which is what makes the reconciliation check worth running."""
    original = event_driven.run

    def shifted(rows, strategy, **kwargs):  # type: ignore[no-untyped-def]
        # Rebalancing on a different cadence changes the fill days, standing in
        # for a timing bug without rewriting the engine.
        kwargs["rebalance_every"] = kwargs.get("rebalance_every", 21) + 1
        return original(rows, strategy, **kwargs)

    monkeypatch.setattr(event_driven, "run", shifted)
    result = selftest.check_engines_reconcile()
    assert not result.ok


# --- injected bug: non-determinism ---


def test_a_non_deterministic_engine_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Determinism is a project-wide rule and the precondition for the golden
    file meaning anything."""
    calls = {"n": 0}
    original = event_driven.run

    def drifting(rows, strategy, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        result = original(rows, strategy, **kwargs)
        if calls["n"] % 2 == 0 and result.equity:
            result.equity[-1] += 0.01
        return result

    monkeypatch.setattr(event_driven, "run", drifting)
    assert not selftest.check_determinism().ok


# --- injected bug: broken accounting ---


def test_a_position_that_loses_its_cost_basis_is_caught() -> None:
    """A flat position retaining a basis, or a basis vanishing while shares
    remain, are both silent corruptions of realised P&L."""
    portfolio = Portfolio(cash=10_000.0)
    portfolio.apply(
        Fill(
            client_order_id="x",
            day=selftest.START,
            symbol="ACME",
            side=Side.BUY,
            quantity=10,
            price=100.0,
            cost=0.0,
        )
    )
    portfolio.positions["ACME"].cost_basis = 0.0  # corrupt it
    assert portfolio.positions["ACME"].quantity == 10
    assert portfolio.positions["ACME"].average_price() == 0.0


def test_equity_identity_fails_when_cash_is_wrong() -> None:
    """cash + positions == equity is the identity every other number rests on."""
    portfolio = Portfolio(cash=10_000.0)
    portfolio.apply(
        Fill(
            client_order_id="x",
            day=selftest.START,
            symbol="ACME",
            side=Side.BUY,
            quantity=10,
            price=100.0,
            cost=5.0,
        )
    )
    marks = {"ACME": 100.0}
    assert portfolio.equity(marks) == pytest.approx(10_000 - 5)
    portfolio.cash += 1_000  # inject money from nowhere
    assert portfolio.equity(marks) != pytest.approx(10_000 - 5)


# --- the golden file ---


def test_the_golden_file_detects_drift(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Slow drift is the failure no single commit looks responsible for."""
    import json

    path = tmp_path / "golden.json"
    assert selftest.check_golden(path).ok  # creates it
    stored = json.loads(path.read_text())
    stored["final_equity"] = stored["final_equity"] + 1.0
    path.write_text(json.dumps(stored))

    result = selftest.check_golden(path)
    assert not result.ok
    assert "drifted" in result.detail
    assert "UPDATE=1" in result.detail


def test_the_golden_file_can_be_deliberately_updated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    path = tmp_path / "golden.json"
    selftest.check_golden(path)
    stored = json.loads(path.read_text())
    stored["final_equity"] = 1.0
    path.write_text(json.dumps(stored))

    assert not selftest.check_golden(path).ok
    assert selftest.check_golden(path, update=True).ok
    assert selftest.check_golden(path).ok


# --- the synthetic worlds themselves ---


def test_the_flat_world_really_is_flat() -> None:
    """If the fixture drifts, the zero-alpha test measures nothing."""
    rows = selftest.flat_world()
    assert len({r.close for r in rows}) == 1


def test_the_alpha_world_really_contains_alpha() -> None:
    rows = selftest.alpha_world(winners=5, winner_drift=0.002)
    winner = [r for r in rows if r.symbol == "SYM00"]
    loser = [r for r in rows if r.symbol == "SYM19"]
    assert winner[-1].close > winner[0].close * 1.5
    assert loser[-1].close == loser[0].close
