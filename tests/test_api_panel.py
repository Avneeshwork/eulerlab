"""The shared panel cache, and the key that stops it serving the wrong index.

`_Panel` holds one copy of a 540 MB panel and a cache of back-adjusted price
indices. The index cache was keyed by the day-window alone, which was safe only
while every run saw every symbol. Once runs can be restricted to a universe,
that key is a silent correctness bug.
"""

from __future__ import annotations

from datetime import date

import pytest

from eulerlab.api.server import _Panel, _universe_rows
from eulerlab.features.panel import PanelRow


def _row(symbol: str, day: date, close: float) -> PanelRow:
    return PanelRow(day=day, symbol=symbol, close=close, volume=1000.0, turnover=close * 1000.0)


def test_the_index_cache_is_keyed_by_universe_not_only_by_window() -> None:
    """The bug this pins: a nifty50 run at 800 days would hand its index to the
    next 800-day run over every symbol, which then has no adjusted prices for
    the symbols nifty50 never contained. Same window, different row set, and
    the second run reads the first run's prices."""
    panel = _Panel()
    day = date(2026, 1, 2)
    narrow = [_row("AAA", day, 100.0)]
    wide = [_row("AAA", day, 100.0), _row("BBB", day, 200.0)]

    first = panel.index(800, narrow, "nifty50")
    second = panel.index(800, wide, "all")

    assert set(first) == {"AAA"}
    assert set(second) == {"AAA", "BBB"}, "the wide run must not be served the narrow index"


def test_the_same_window_and_universe_is_still_cached() -> None:
    """The fix must not turn the cache off."""
    panel = _Panel()
    rows = [_row("AAA", date(2026, 1, 2), 100.0)]
    assert panel.index(800, rows, "all") is panel.index(800, rows, "all")


def test_all_means_every_symbol_in_the_panel() -> None:
    rows = [_row("AAA", date(2026, 1, 2), 1.0), _row("BBB", date(2026, 1, 2), 2.0)]
    kept, size, resolved = _universe_rows(rows, "all")
    assert kept == rows
    assert size == 2
    assert resolved == [], "a named universe resolves by name; only a custom list is enumerated"


def test_a_hand_picked_list_overrides_the_universe() -> None:
    """Batches are a convenience, not the only way in. "Does this work on these
    two names" was previously unaskable."""
    rows = [
        _row("AAA", date(2026, 1, 2), 1.0),
        _row("BBB", date(2026, 1, 2), 2.0),
        _row("CCC", date(2026, 1, 2), 3.0),
    ]
    kept, size, resolved = _universe_rows(rows, "all", ["aaa", "CCC"])
    assert {row.symbol for row in kept} == {"AAA", "CCC"}, "case is normalised"
    assert size == 2
    assert resolved == ["AAA", "CCC"]


def test_choosing_instruments_the_panel_does_not_have_refuses() -> None:
    """Rather than running on the empty intersection and reporting no trades,
    which reads as "no edge" when the truth is "nothing was there"."""
    rows = [_row("AAA", date(2026, 1, 2), 1.0)]
    with pytest.raises(RuntimeError, match="none of the"):
        _universe_rows(rows, "all", ["ZZZ"])


def test_search_covers_every_asset_class_with_data() -> None:
    """It returned equities and nothing else, which quietly meant the landed
    crypto pairs and mutual fund schemes could not be seen or selected at all.
    An asset class with data and no way to reach it is the same defect as one
    offered without data, pointing the other way."""
    from eulerlab.strategies import catalog

    classes = {i.asset_class.value for i in catalog.search(limit=90)}
    on_disk = {c.asset_class.value for c in catalog.capabilities() if c.supported}
    assert classes == on_disk, "a bare search must reach every class that has data"


def test_a_fund_scheme_appears_once_not_once_per_isin() -> None:
    """AMFI publishes one row per ISIN and a scheme has two — growth/payout and
    reinvestment. A picker offers a scheme to backtest, not an ISIN variant."""
    from eulerlab.strategies import catalog

    funds = catalog.fund_instruments(limit=40)
    codes = [f.symbol for f in funds]
    assert len(codes) == len(set(codes))


def test_a_fund_carries_a_name_because_its_code_is_not_one() -> None:
    from eulerlab.strategies import catalog

    funds = catalog.fund_instruments(limit=5)
    assert funds, "no enriched snapshot on disk"
    assert all(f.name for f in funds), "119551 tells nobody anything"


def test_costs_are_modelled_only_where_a_schedule_exists() -> None:
    """costs/schedule.py covers Indian exchange-traded segments. A Binance spot
    trade pays a taker fee and a fund redemption may pay an exit load; neither
    pays STT or stamp duty. Running them through EQUITY_DELIVERY would produce a
    confidently wrong number rather than an obviously missing one (S-028)."""
    from eulerlab.api.server import cost_mode_for

    assert cost_mode_for("equity") == "realistic"
    assert cost_mode_for("crypto") == "replication"
    assert cost_mode_for("mutual_fund") == "replication"


def test_the_index_key_separates_asset_classes() -> None:
    """Equity, crypto and fund panels all call their universe "all". Sharing one
    cache entry handed a fund run an index of Binance pairs — KeyError on a
    scheme code."""
    from eulerlab.api.server import index_key

    assert index_key("all", [], "equity") != index_key("all", [], "crypto")
    assert index_key("all", [], "crypto") != index_key("all", [], "mutual_fund")


def test_the_index_key_separates_two_hand_picked_lists() -> None:
    from eulerlab.api.server import index_key

    assert index_key("all", ["AAA", "BBB"]) != index_key("all", ["AAA", "CCC"])
    assert index_key("all", ["BBB", "AAA"]) == index_key("all", ["AAA", "BBB"]), (
        "order must not matter; the set is what identifies the run"
    )


def test_equity_params_are_unchanged_by_the_new_fields() -> None:
    """`instruments` and `asset_class` join the params only when they are not
    the default. An always-present key would change the configuration hash of
    every run already recorded, inflating the denominator that prices selection
    bias for no reason but a new dict key."""
    from eulerlab.api.server import BatchRunRequest, _run_params

    plain = _run_params(BatchRunRequest(strategies=["s"], days=800, universe="all"))
    assert set(plain) == {"days", "tier", "universe"}
