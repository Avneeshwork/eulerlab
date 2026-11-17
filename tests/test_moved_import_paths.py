"""The old import paths of the strategy and sizing modules still work (ADR-219).

The strategies moved to `eulerlab.strategies`, one file per strategy, and the
sizing models and loss limits to `eulerlab.risk`. The old
modules are shims for code written before the move; each must hand back the
very same objects as the new path, not copies.
"""

from __future__ import annotations

import importlib

import pytest

MOVED = {
    "eulerlab.backtest.india_papers": ("eulerlab.strategies.daily.india_papers", "STRATEGIES"),
    "eulerlab.backtest.evidence_daily": ("eulerlab.strategies.daily.evidence", "STRATEGIES"),
    "eulerlab.backtest.github_daily": ("eulerlab.strategies.daily.github", "STRATEGIES"),
    "eulerlab.backtest.events_daily": ("eulerlab.strategies.daily.events", "STRATEGIES"),
    "eulerlab.backtest.screener_models": ("eulerlab.strategies.daily.screener", "STRATEGIES"),
    "eulerlab.backtest.published": ("eulerlab.strategies.daily.published", "BUILDERS"),
    "eulerlab.intraday.papers": ("eulerlab.strategies.intraday.papers", "SIGNALS"),
    "eulerlab.intraday.india": ("eulerlab.strategies.intraday.india", "INDIA_SIGNALS"),
    "eulerlab.intraday.crypto_signals": ("eulerlab.strategies.intraday.crypto", "CRYPTO_SIGNALS"),
    "eulerlab.deploy.sizing_models": ("eulerlab.risk.sizing", "size_book"),
    "eulerlab.deploy.sizing": ("eulerlab.risk.sizing", "fit_to_capital"),
    "eulerlab.deploy.loss_limits": ("eulerlab.risk.limits.loss_limits", "apply"),
}


@pytest.mark.parametrize("old", sorted(MOVED))
def test_the_old_path_gives_the_new_objects(old: str) -> None:
    new, table = MOVED[old]
    before, after = importlib.import_module(old), importlib.import_module(new)
    assert getattr(before, table) is getattr(after, table)
    for name in after.__all__:
        assert getattr(before, name) is getattr(after, name), name
