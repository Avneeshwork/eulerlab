"""The (i) button must describe the engine that actually ran.

`explain`'s own docstring says a page explaining a run the code does not
perform is worse than no explanation — and it was doing exactly that for all
twenty swept signals, describing rebalance days and target weights to someone
reading an intraday bracket result. ADR-037 is explicit that a bracket trade
cannot be expressed as target weights, so this was not a loose analogy.
"""

from __future__ import annotations

from eulerlab.api.server import explain


def _titles(strategy: str) -> list[str]:
    return [section["title"] for section in explain(strategy)["procedure"]]


def _body(strategy: str, title: str) -> str:
    for section in explain(strategy)["procedure"]:
        if section["title"] == title:
            return str(section["body"])
    return ""


def test_an_intraday_signal_is_not_described_as_rebalancing() -> None:
    """It names the absence explicitly rather than staying silent about it.

    A reader arriving from the daily engine expects weights and a rebalance,
    so the useful thing is to say those do not apply here — which is why the
    words appear, negated, instead of being scrubbed.
    """
    body = _body("orb_breakout", "What a backtest here is").lower()
    assert "bracket" in body
    assert "no rebalance" in body
    assert "no target weights" in body
    # And none of the daily engine's actual mechanics.
    assert "rebalances every" not in body
    assert "account starts at" not in body


def test_a_daily_strategy_still_gets_the_daily_description() -> None:
    body = _body("momentum_12_1", "What a backtest here is")
    assert "rebalance" in body.lower()


def test_intraday_sections_are_intraday_only() -> None:
    """Tier A / Tier B is a daily-engine distinction and does not apply."""
    intraday = _titles("orb_breakout")
    assert "Tier A and Tier B" not in intraday
    assert "What a sweep costs" in intraday
    assert "Why the rejections are counted" in intraday

    daily = _titles("momentum_12_1")
    assert "Tier A and Tier B" in daily
    assert "What a sweep costs" not in daily


def test_shared_sections_appear_on_both() -> None:
    for strategy in ("orb_breakout", "momentum_12_1"):
        titles = _titles(strategy)
        assert "What it cannot see" in titles
        assert "What the Sharpe is measured against" in titles
        assert "Warmup" in titles


def test_the_intraday_warmup_is_the_one_the_engine_uses() -> None:
    """80 bars, not "a quarter of the window capped at 253 days"."""
    from eulerlab.intraday.paper_scan import WARMUP_BARS

    assert str(WARMUP_BARS) in _body("orb_breakout", "Warmup")


def test_costs_name_all_three_venues() -> None:
    """The fifty-fold gap between them decides more results than any parameter."""
    body = _body("orb_breakout", "What the costs are")
    assert "0.118" in body  # Delta
    assert "0.002" in body  # US equity
    assert "STT" in body  # NSE


def test_a_crypto_signal_with_a_paper_shows_it() -> None:
    """`par_deviation` cites Cohen (2023) and displayed no source.

    Its declaration is built on the crypto branch, which never populated
    `paper_url`; only the paper-signal branch did. Resolving from the citation
    means one missed branch cannot hide provenance again.
    """
    about = explain("par_deviation")["strategy"]
    assert about is not None
    assert "aimspress" in about["paper_url"]
