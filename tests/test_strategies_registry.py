"""The registry and the catalogue.

The theme of these tests is that the console must not be able to show something
the system cannot produce. A stage nothing can reach, a Sharpe nobody measured,
or a market with no data behind it are all the same class of defect: an
interface asserting more than the evidence supports.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab.strategies import REGISTRY, AssetClass, Stage, Timeframe, catalog, fleet
from eulerlab.validation import ledger


def _ledger(tmp_path: Path, subject: str, sharpe: float | None) -> Path:
    path = tmp_path / "l.jsonl"
    outcome: dict[str, object] = {} if sharpe is None else {ledger.SHARPE_KEY: sharpe}
    ledger.append(kind="validation", subject=subject, params={}, outcome=outcome, path=path)
    return path


def test_a_strategy_with_no_evidence_reports_none_not_zero(tmp_path: Path) -> None:
    """The distinction the whole list rests on. Zero is a measurement meaning
    'no edge'; None means nobody looked. Rendering the second as the first
    invents a result."""
    rows = {r.declaration.id: r for r in fleet(tmp_path / "empty.jsonl")}
    assert rows["buy_and_hold"].sharpe is None
    assert rows["buy_and_hold"].trials == 0


def test_stage_is_derived_from_the_ledger(tmp_path: Path) -> None:
    # Seeded as a `validation` entry by _ledger, which is what actually
    # constitutes running the strategy — an `ic` entry would not.
    path = _ledger(tmp_path, "H-0001", 1.27)
    rows = {r.declaration.id: r for r in fleet(path)}
    assert rows["momentum_12_1"].stage is Stage.BACKTESTED
    # No ledger entry names it, so it cannot have been evaluated.
    assert rows["buy_and_hold"].stage is Stage.REGISTERED


def test_no_strategy_can_reach_a_stage_the_system_cannot_produce(tmp_path: Path) -> None:
    """`forward_testing` and `live` have no mechanism behind them. A console
    that can display them will eventually display one that is not true."""
    path = _ledger(tmp_path, "H-0001", 1.27)
    unreachable = {Stage.FORWARD_TESTING, Stage.LIVE, Stage.RETIRED}
    assert not [r for r in fleet(path) if r.stage in unreachable]


def test_the_fleet_order_is_stable(tmp_path: Path) -> None:
    """A list whose rows move between refreshes is one nobody can point at."""
    path = _ledger(tmp_path, "H-0001", 1.0)
    first = [r.declaration.id for r in fleet(path)]
    assert first == [r.declaration.id for r in fleet(path)]
    assert first == sorted(first)


def test_tweezer_is_recorded_as_not_a_strategy_subclass() -> None:
    """Its data cannot be expressed in a `MarketView` at all (ADR-037). Keeping
    the reason in the declaration stops it reading as an oversight."""
    assert REGISTRY["tweezer_bottom"].is_strategy_subclass is False
    assert REGISTRY["momentum_12_1"].is_strategy_subclass is True


def test_no_strategy_claims_a_risk_manager_that_does_not_exist() -> None:
    """RM/TM are not built (ADR-036), so a declaration may only name one if the
    code behind it exists.

    The exemption is not a list of strategy ids, it is a property: everything
    running through the intraday bracket executor really does size by risk
    percent and really does exit on a stop, because `_plan` and `bracket.run`
    are that code. Everything on the daily engine is flat equal-weight and must
    say so rather than describing a sizer it does not have.

    This started as "only tweezer_bottom", which was true when Tweezer was the
    only bracket strategy and became wrong the moment ten more were coded
    against the same executor — and wrong again when ten crypto signals joined
    them, and again when four NSE adaptations did.

    It claimed to express a property and was still enumerating modules:
    `{*SIGNALS, *CRYPTO_SIGNALS}` has to be edited every time a fourth source
    of bracket signals appears, which is exactly what a list does. `ALL_SIGNALS`
    is the property — it is what `paper_scan` dispatches on, so a signal is
    bracketed if and only if the scanner can run it, and the next addition
    genuinely is free.
    """
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    bracketed = {"tweezer_bottom", *ALL_SIGNALS}
    for declaration in REGISTRY.values():
        if declaration.id not in bracketed:
            assert declaration.risk_manager == "", declaration.id
            assert declaration.trade_manager == "", declaration.id
        else:
            assert declaration.risk_manager == "risk-pct", declaration.id
            assert declaration.trade_manager == "bracket", declaration.id


# --- the catalogue ---------------------------------------------------------


def test_unsupported_markets_are_reported_not_hidden() -> None:
    """An empty result reads as 'no trades found'. The truth is 'never
    measured', and the matrix is where that distinction lives."""
    matrix = {(c.asset_class, c.timeframe): c for c in catalog.capabilities()}
    assert matrix[(AssetClass.EQUITY, Timeframe.DAILY)].supported

    # Options, and only options, as the standing example. Crypto and FX were
    # each used here and each went stale — crypto when the Binance archive
    # landed, FX when the FXCM one did, and FX again in the other direction
    # when a prune moved its bytes to B2 and the offline suite could no longer
    # reach them. Anything whose support depends on which files happen to be
    # on this disk is a moving target and does not belong in an assertion.
    #
    # Options do not move: the chains are parsed and no strategy path reads
    # them, so the cell is false for a reason no ingest can change.
    assert not matrix[(AssetClass.OPTIONS, Timeframe.DAILY)].supported
    # Every unsupported cell explains itself; "no" without a reason is useless.
    assert all(c.detail for c in catalog.capabilities() if not c.supported)


def test_the_capability_check_reads_the_real_panel_path() -> None:
    """Regression: this checked `panel.parquet` while the panel is
    `price_panel.jsonl`, and so reported 'not built' for 540 MB of data sitting
    on disk — the exact failure the matrix exists to prevent, one level up."""
    from eulerlab.features.panel import PANEL_PATH

    daily = next(
        c
        for c in catalog.capabilities()
        if c.asset_class is AssetClass.EQUITY and c.timeframe is Timeframe.DAILY
    )
    if PANEL_PATH.exists():
        assert "present" in daily.detail
    else:
        assert "not built" in daily.detail


def test_batches_are_nested_slices_of_one_ranking() -> None:
    assert catalog.universe("nifty50") == catalog.universe("nifty250")[:50]
    assert len(catalog.universe("nifty100")) == 100


def test_an_unknown_batch_raises_rather_than_returning_nothing() -> None:
    """Returning [] would read as 'no instruments match', which is a different
    and much quieter failure than 'that batch does not exist'."""
    with pytest.raises(ValueError, match="unknown batch"):
        catalog.universe("sensex30")


def test_the_batch_caveat_names_the_bias_it_prevents() -> None:
    """Everyone reading a chip labelled `nifty50` will assume index membership.
    The caveat travels with the data, not in the page."""
    assert "survivorship" in catalog.UNIVERSE_CAVEAT
    assert "not index membership" in catalog.UNIVERSE_CAVEAT


def test_search_is_case_insensitive_and_bounded() -> None:
    found = catalog.search("reliance", batch="nifty250")
    assert [i.symbol for i in found][:1] == ["RELIANCE"]
    assert len(catalog.search("", batch="nifty250", limit=7)) == 7


# --- the published set ------------------------------------------------------


def test_every_registered_strategy_can_actually_be_built() -> None:
    """A console that lists a strategy it cannot run is a console that lies.

    The registry and the builders are separate structures, so nothing but this
    stops one gaining an entry the other lacks.
    """
    from eulerlab.backtest.published import BUILDERS

    runnable = set(BUILDERS) | {"buy_and_hold"}
    declared = {d.id for d in REGISTRY.values() if d.is_strategy_subclass}
    missing = declared - runnable
    assert not missing, f"declared but unbuildable: {sorted(missing)}"


def test_ten_published_strategies_are_registered() -> None:
    from eulerlab.backtest.india_papers import BUILDERS as INDIA
    from eulerlab.backtest.published import BUILDERS

    # The ten from docs/RESEARCH/017, plus one per Indian-equity paper (064).
    assert len(BUILDERS) == 10 + len(INDIA)
    for name in BUILDERS:
        assert name in REGISTRY, f"{name} builds but is not declared"


def test_an_ic_trial_does_not_make_a_strategy_backtested(tmp_path: Path) -> None:
    """An `ic` entry evaluates a FEATURE — its rank correlation with forward
    returns — not the strategy that ranks on it.

    Counting one as a backtest let `short_term_reversal` report "backtested"
    because somebody once IC-screened `reversal_1m`, which is a different claim
    about a different object. The trial still counts toward the bar, because
    the search really happened; only the stage is withheld.
    """
    path = tmp_path / "l.jsonl"
    ledger.append(kind="ic", subject="reversal_1m", params={}, outcome={"mean_ic": 0.01}, path=path)
    rows = {r.declaration.id: r for r in fleet(path)}
    row = rows["short_term_reversal"]

    assert row.trials == 1, "the search happened and is counted"
    assert row.stage is Stage.REGISTERED, "but the strategy was never run"


def test_a_validation_trial_does_make_it_backtested(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    ledger.append(
        kind="validation",
        subject="H-0001",
        params={},
        outcome={ledger.SHARPE_KEY: 1.27},
        path=path,
    )
    rows = {r.declaration.id: r for r in fleet(path)}
    assert rows["momentum_12_1"].stage is Stage.BACKTESTED
    assert rows["momentum_12_1"].sharpe == 1.27


def test_the_composite_drops_symbols_not_scored_by_every_feature() -> None:
    """A symbol ranked by two of three features is not comparable to one ranked
    by all three, so averaging over fewer would flatter it."""
    from eulerlab.backtest.published import Composite

    composite = Composite(["low_volatility", "max_drawdown"], top_n=5)
    # `lookback` is Optional on the base class; a Composite always sets one.
    assert composite.lookback is not None
    assert composite.lookback >= 126
    assert "low_volatility" in composite.name
    assert "max_drawdown" in composite.name
