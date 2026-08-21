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
    path = _ledger(tmp_path, "H-0001", 1.27)
    rows = {r.declaration.id: r for r in fleet(path)}
    assert rows["rank_and_hold"].stage is Stage.BACKTESTED
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
    assert REGISTRY["rank_and_hold"].is_strategy_subclass is True


def test_no_strategy_claims_a_risk_manager_that_does_not_exist() -> None:
    """RM/TM are not built (ADR-036). Only Tweezer names any, because its
    bracket executor is real code; the rest must report none rather than a
    sizer they do not have."""
    for declaration in REGISTRY.values():
        if declaration.id != "tweezer_bottom":
            assert declaration.risk_manager == ""
            assert declaration.trade_manager == ""


# --- the catalogue ---------------------------------------------------------


def test_unsupported_markets_are_reported_not_hidden() -> None:
    """An empty result reads as 'no trades found'. The truth is 'never
    measured', and the matrix is where that distinction lives."""
    matrix = {(c.asset_class, c.timeframe): c for c in catalog.capabilities()}
    assert matrix[(AssetClass.EQUITY, Timeframe.DAILY)].supported
    assert not matrix[(AssetClass.CRYPTO, Timeframe.DAILY)].supported
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
