"""Paper trading against the backtest that authorised it.

The headline test is the frictionless one: with a broker that fills at the
engine's price, a paper run must reproduce the backtest **exactly**. They
share one loop, one strategy, one sizing path and one cost model, so any
difference at all is the order path drifting from the engine — which is the
divergence `CLAUDE.md` says to stop and fix rather than to explain.

The decomposition tests check that the split closes to the paisa. That is a
weaker claim than it looks and the module says so: both books are ours, so the
attribution is an identity. It is worth testing anyway, because an identity
that does not close means a term is missing.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.backtest import event_driven
from eulerlab.backtest.execution import SimulatedExecutor
from eulerlab.backtest.strategies import BuyAndHold
from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.features.panel import PanelRow
from eulerlab.oms.paper_broker import PaperFaults
from eulerlab.paper import attribution, runner

START = date(2024, 1, 1)


def _panel(n_symbols: int = 12, n_days: int = 150, drift: float = 0.001) -> list[PanelRow]:
    rows: list[PanelRow] = []
    for s in range(n_symbols):
        price = 100.0 + s
        for d in range(n_days):
            price *= 1.0 + drift
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"SYM{s:03d}",
                    close=price,
                    volume=1000.0,
                    turnover=1e9 - s,
                    isin=f"TEST{s:06d}",
                )
            )
    return rows


def _compare(tmp_path: Path, **kwargs: object) -> attribution.Attribution:
    return attribution.compare(
        _panel(),
        BuyAndHold(top_n=6),
        root=tmp_path,
        rebalance=20,
        warmup=30,
        **kwargs,  # type: ignore[arg-type]
    )


# --- the headline -----------------------------------------------------------


def test_a_frictionless_paper_run_reproduces_the_backtest_exactly(tmp_path: Path) -> None:
    """Not 'closely'. Exactly. There is one loop, and the only thing that
    differs is who fills the order."""
    result = _compare(tmp_path)
    assert result.paper_equity == result.backtest_equity
    assert result.gap == 0.0
    assert result.trades_backtest_only == 0
    assert result.trades_paper_only == 0


def test_the_paper_path_actually_placed_the_orders(tmp_path: Path) -> None:
    """Guards the way the test above could pass for the wrong reason: a paper
    run that traded nothing would also match a backtest that traded nothing."""
    rows = _panel()
    oms = runner.fresh_oms(tmp_path)
    outcome = runner.run(rows, BuyAndHold(top_n=6), oms=oms, rebalance=20, warmup=30)
    assert outcome.executor.submitted > 0
    assert len(outcome.result.fills) > 0
    assert oms.adapter.positions()
    assert outcome.reconciliation.clean


def test_the_executor_is_the_only_difference(tmp_path: Path) -> None:
    """The same engine call with the default executor and with the OMS
    executor, on the same inputs, must agree."""
    rows = _panel()
    index = build_adjusted_index(rows)
    plain = event_driven.run(
        rows, BuyAndHold(top_n=6), rebalance_every=20, warmup=30, adjusted_index=index
    )
    explicit = event_driven.run(
        rows,
        BuyAndHold(top_n=6),
        rebalance_every=20,
        warmup=30,
        adjusted_index=index,
        executor=SimulatedExecutor(),
    )
    assert plain.equity == explicit.equity


# --- the decomposition ------------------------------------------------------


def test_slippage_makes_paper_worse_and_the_split_still_closes(tmp_path: Path) -> None:
    result = _compare(tmp_path, slippage_bps=50.0)
    assert result.gap < 0.0, "adverse slippage should cost money"
    assert result.closes, f"residual {result.residual}"
    slippage = next(c for c in result.components if c.name.startswith("slippage"))
    assert slippage.rupees < 0.0


def test_rejections_show_up_as_trades_paper_did_not_make(tmp_path: Path) -> None:
    result = _compare(tmp_path, reject_symbols={"SYM000", "SYM001"})
    assert result.trades_backtest_only > 0
    assert result.closes, f"residual {result.residual}"


def test_the_residual_is_checked_against_a_paisa_not_a_percentage() -> None:
    """A 10% threshold on an exact identity is a check that cannot fail."""
    assert attribution.CLOSES_TO == 0.01


def test_a_missing_term_would_be_caught() -> None:
    """The closing test has to be able to fail, so drop a component and check
    it does."""
    rows = _panel()
    index = build_adjusted_index(rows)
    backtest = event_driven.run(
        rows, BuyAndHold(top_n=6), rebalance_every=20, warmup=30, adjusted_index=index
    )
    faked = event_driven.run(
        rows, BuyAndHold(top_n=4), rebalance_every=20, warmup=30, adjusted_index=index
    )
    result = attribution.attribute(backtest, faked, marks={})
    assert not result.closes, "an unexplained gap was reported as closing"


def test_the_report_states_what_the_residual_does_not_prove(tmp_path: Path) -> None:
    text = _compare(tmp_path, slippage_bps=50.0).render()
    assert "identity" in text
    assert "not that live execution is understood" in text


# --- the paper runner -------------------------------------------------------


def test_a_paper_run_recovers_before_it_trades(tmp_path: Path) -> None:
    """Starting a session with orders in an unknown state and sending more on
    top is how a bad morning becomes a bad week."""
    rows = _panel()
    oms = runner.fresh_oms(tmp_path, faults=PaperFaults(unreachable_on_place=1))
    runner.run(rows, BuyAndHold(top_n=6), oms=oms, rebalance=20, warmup=30)
    assert oms.unresolved() == [], "an order was left UNKNOWN across the run"


def test_a_paper_run_is_repeatable(tmp_path: Path) -> None:
    rows = _panel()
    equities = []
    for name in ("a", "b"):
        oms = runner.fresh_oms(tmp_path / name)
        outcome = runner.run(rows, BuyAndHold(top_n=6), oms=oms, rebalance=20, warmup=30)
        equities.append(outcome.result.equity)
    assert equities[0] == equities[1]


def test_the_paper_report_names_the_simulation(tmp_path: Path) -> None:
    oms = runner.fresh_oms(tmp_path)
    outcome = runner.run(_panel(), BuyAndHold(top_n=6), oms=oms, rebalance=20, warmup=30)
    assert "paper run" in outcome.render()
    assert outcome.result.final_equity == pytest.approx(outcome.result.final_equity)


def test_a_timeout_mid_run_is_resolved_and_costs_nothing(tmp_path: Path) -> None:
    """A send that timed out but did land should end up filled at the same
    price, so a frictionless run with a timeout in it STILL reproduces the
    backtest exactly. If it does not, the timeout cost us a position."""
    result = attribution.compare(
        _panel(),
        BuyAndHold(top_n=6),
        root=tmp_path,
        rebalance=20,
        warmup=30,
        faults=PaperFaults(unreachable_on_place=1),
    )
    assert result.gap == 0.0
