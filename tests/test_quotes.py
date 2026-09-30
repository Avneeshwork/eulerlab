"""Live quotes — source precedence and how absence is reported."""

from __future__ import annotations

from eulerlab import quotes


def _q(symbol: str, last: float, prev: float, source: str) -> quotes.Quote:
    return quotes.Quote(
        symbol=symbol, last=last, previous_close=prev, source=source, at="2026-08-23T12:00:00+00:00"
    )


def test_change_is_measured_against_the_previous_close() -> None:
    assert _q("X", 110.0, 100.0, "zerodha").change_pct == 10.0
    assert _q("X", 90.0, 100.0, "zerodha").change_pct == -10.0


def test_a_missing_previous_close_reports_no_change_not_infinity() -> None:
    """Dividing by a zero close would render as Infinity or NaN on the page,
    which reads as a data error rather than as a missing input."""
    assert _q("X", 110.0, 0.0, "zerodha").change_pct == 0.0


def test_the_source_is_recorded_per_quote_not_per_run() -> None:
    """A fallback that covered half the universe would otherwise be
    indistinguishable from one that covered all of it."""
    result = quotes.QuoteResult()
    result.quotes["A"] = _q("A", 1.0, 1.0, "zerodha")
    result.quotes["B"] = _q("B", 2.0, 2.0, "yahoo")
    result.sources = {"zerodha": 1, "yahoo": 1}
    assert result.quotes["A"].source != result.quotes["B"].source


def test_the_broker_is_the_primary_source() -> None:
    """Zerodha is the venue this platform trades through, so its quote is the
    price an order would actually meet. Yahoo has no such relationship."""
    result = quotes.QuoteResult(sources={"zerodha": 20, "yahoo": 3})
    assert result.primary_source == "zerodha"


def test_no_quotes_is_reported_as_not_live() -> None:
    """An empty band must not read as "nothing moved"."""
    assert not quotes.QuoteResult().live
    assert quotes.QuoteResult().primary_source == ""


def test_asking_for_nothing_asks_no_source() -> None:
    """A bare call must not spend a broker request to learn it had no work."""
    result = quotes.live([])
    assert result.quotes == {} and result.errors == {}


def test_symbols_are_deduplicated_and_normalised() -> None:
    """Gainers, losers and unusual volume overlap, and a duplicate symbol is a
    duplicate quote request on a page that has to stay fast."""
    seen: list[list[str]] = []

    def fake(symbols: list[str]) -> tuple[dict[str, quotes.Quote], str]:
        seen.append(symbols)
        return {}, "stubbed"

    original = quotes.from_zerodha
    quotes.from_zerodha = fake
    try:
        quotes.live(["reliance", "RELIANCE", " TCS ", "TCS"])
    finally:
        quotes.from_zerodha = original

    assert seen and seen[0] == ["RELIANCE", "TCS"]
