"""Codegen composes vetted primitives and never writes Python.

The refusal is the design. Executing generated source would discard Sprint 4's
firewall — arbitrary code can open the panel file directly, while a `Strategy`
receiving a `MarketView` physically cannot see past its date.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eulerlab.backtest.strategies import BuyAndHold, RankAndHold
from eulerlab.research import codegen


def _card(tmp_path: Path, configs: list[dict[str, object]]) -> Path:
    path = tmp_path / "H-0099.yaml"
    path.write_text(yaml.safe_dump({"id": "H-0099", "configurations": configs}), encoding="utf-8")
    return path


def test_a_card_builds_one_strategy_per_configuration() -> None:
    built = codegen.build_from_card(Path("hypotheses/H-0002.yaml"))
    assert len(built) == 4
    assert all(isinstance(b.strategy, RankAndHold) for b in built)


def test_every_declared_configuration_is_built_none_filtered(tmp_path: Path) -> None:
    """The card fixed this list in advance and PBO is computed across exactly
    it. Dropping one because it looks unpromising is the selection effect the
    apparatus exists to measure."""
    configs = [
        {"feature": "momentum_12_1", "top_n": 10},
        {"feature": "momentum_12_1", "top_n": 20},
        {"feature": "momentum_12_1", "top_n": 30},
    ]
    assert len(codegen.build_from_card(_card(tmp_path, configs))) == 3


def test_an_unknown_feature_raises_rather_than_being_skipped(tmp_path: Path) -> None:
    """Silently building fewer strategies would evaluate the card on a
    different set from the one it pre-registered."""
    path = _card(tmp_path, [{"feature": "does_not_exist", "top_n": 30}])
    with pytest.raises(codegen.UnknownPrimitive, match="unknown feature"):
        codegen.build_from_card(path)


def test_an_unknown_shape_raises(tmp_path: Path) -> None:
    path = _card(tmp_path, [{"shape": "neural_net", "top_n": 30}])
    with pytest.raises(codegen.UnknownPrimitive, match="unknown shape"):
        codegen.build_from_card(path)


def test_a_card_with_no_configurations_raises(tmp_path: Path) -> None:
    with pytest.raises(codegen.UnknownPrimitive, match="no configurations"):
        codegen.build_from_card(_card(tmp_path, []))


def test_the_buy_and_hold_shape_is_available(tmp_path: Path) -> None:
    built = codegen.build_from_card(_card(tmp_path, [{"shape": "buy_and_hold", "top_n": 20}]))
    assert isinstance(built[0].strategy, BuyAndHold)


def test_a_liquidity_floor_is_carried_into_the_strategy(tmp_path: Path) -> None:
    built = codegen.build_from_card(
        _card(tmp_path, [{"feature": "momentum_12_1", "top_n": 30, "min_turnover": 5e7}])
    )
    strategy = built[0].strategy
    assert isinstance(strategy, RankAndHold)
    assert strategy.min_turnover == 5e7


def test_labels_distinguish_configurations(tmp_path: Path) -> None:
    """PBO indexes by configuration; two that share a label would be one."""
    built = codegen.build_from_card(
        _card(
            tmp_path,
            [
                {"feature": "momentum_12_1", "top_n": 30, "rebalance": 21},
                {"feature": "momentum_12_1", "top_n": 30, "rebalance": 63},
            ],
        )
    )
    assert built[0].label != built[1].label


def test_generated_strategies_are_the_normal_interface() -> None:
    """No wrapper, no privileged access — the same object both engines run, so
    Sprint 4's firewall applies unchanged."""
    from eulerlab.backtest.strategy import Strategy

    for b in codegen.build_from_card(Path("hypotheses/H-0002.yaml")):
        assert isinstance(b.strategy, Strategy)
        assert hasattr(b.strategy, "target_weights")


def test_the_library_is_documented_for_card_authors() -> None:
    text = codegen.describe_library()
    assert "momentum_12_1" in text
    assert "rank_and_hold" in text
    assert "tested by hand" in text
