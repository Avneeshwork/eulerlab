"""Every strategy is swept on the market its own paper tested.

Before this, `recommended_class="futures"` fell through to the NSE default and
nine signals published on MNQ — the Micro E-Mini Nasdaq 100 future — were being
evaluated on `RELIANCE`. The numbers came out fine; they were answers to a
different question.
"""

from __future__ import annotations

import eulerlab.optimize_run as optimize_run
from eulerlab.strategies import REGISTRY, Declaration


def _swept() -> list[Declaration]:
    return [d for d in REGISTRY.values() if not d.is_strategy_subclass]


def test_futures_papers_route_to_us_bars() -> None:
    """MNQ is a US index future; QQQ tracks the same index in cash form."""
    for declaration in _swept():
        wanted = str(declaration.recommended_class or "").lower()
        if "futures" not in wanted:
            continue
        market, symbol = optimize_run.market_for(declaration)
        assert market == "us", f"{declaration.id} swept on {market}"
        assert symbol == "QQQ"


def test_crypto_papers_route_to_crypto() -> None:
    for declaration in _swept():
        wanted = str(declaration.recommended_class or "").lower()
        if "crypto" not in wanted:
            continue
        market, symbol = optimize_run.market_for(declaration)
        assert market == "crypto"
        assert symbol == "BTCUSDT"


def test_us_equity_cross_section_paper_gets_a_us_symbol() -> None:
    """Zarattini's opening-range study is ~7,000 US names, not an NSE one."""
    market, symbol = optimize_run.market_for(REGISTRY["orb_in_play"])
    assert market == "us"
    assert symbol == "SPY"


def test_every_swept_strategy_resolves_to_a_known_market() -> None:
    """No strategy silently lands on the default because its class was unread."""
    for declaration in _swept():
        market, symbol = optimize_run.market_for(declaration)
        assert market in {"us", "crypto", "equity"}
        assert symbol
