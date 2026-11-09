"""Live quotes — source precedence and how absence is reported."""

from __future__ import annotations

from typing import Any

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

    original = quotes.from_zerodha, quotes.from_angel, quotes.from_yahoo
    quotes.from_zerodha = fake
    quotes.from_angel = fake
    quotes.from_yahoo = lambda symbols, **_: ({}, "stubbed")
    try:
        quotes.live(["reliance", "RELIANCE", " TCS ", "TCS"])
    finally:
        quotes.from_zerodha, quotes.from_angel, quotes.from_yahoo = original

    assert seen and seen[0] == ["RELIANCE", "TCS"]


def test_angel_covers_what_kite_did_not_before_yahoo(monkeypatch: Any) -> None:
    """Kite's token dies at 06:00; Angel logs itself in, so it is asked next,
    and Yahoo only for what neither priced."""
    asked: dict[str, list[str]] = {}

    def source(name: str, priced: set[str], error: str = "") -> Any:
        def fetch(symbols: list[str], **_: Any) -> tuple[dict[str, quotes.Quote], str]:
            asked[name] = symbols
            return {s: _q(s, 1.0, 1.0, name) for s in symbols if s in priced}, error

        return fetch

    monkeypatch.setattr(quotes, "from_zerodha", source("zerodha", set(), "expired"))
    monkeypatch.setattr(quotes, "from_angel", source("angel", {"SBIN"}))
    monkeypatch.setattr(quotes, "from_yahoo", source("yahoo", set()))
    result = quotes.live(["SBIN", "TCS"])
    assert result.sources == {"angel": 1} and result.primary_source == "angel"
    assert asked["angel"] == ["SBIN", "TCS"] and asked["yahoo"] == ["TCS"]
    assert result.errors == {"zerodha": "expired"}


def test_the_universe_falls_back_to_angel_and_names_both_failures(monkeypatch: Any) -> None:
    monkeypatch.setattr(quotes, "_kite_universe", lambda s: ({}, "Kite token expired"))
    monkeypatch.setattr(
        quotes, "from_angel", lambda s: ({x: _q(x, 2.0, 1.0, "angel") for x in s}, "")
    )
    found, error = quotes.nse_universe(["A", "B"])
    assert set(found) == {"A", "B"} and error == ""
    assert found["A"].source == "angel"

    monkeypatch.setattr(quotes, "from_angel", lambda s: ({}, "login failed"))
    found, error = quotes.nse_universe(["A"])
    assert found == {} and "Kite token expired" in error and "login failed" in error


def test_a_fresh_kite_answer_is_not_second_guessed(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        quotes, "_kite_universe", lambda s: ({x: _q(x, 2.0, 1.0, "zerodha") for x in s}, "")
    )

    def never(symbols: list[str]) -> tuple[dict[str, quotes.Quote], str]:
        raise AssertionError("Angel must not be asked when Kite answered")

    monkeypatch.setattr(quotes, "from_angel", never)
    found, error = quotes.nse_universe(["A"])
    assert found["A"].source == "zerodha" and error == ""


def test_angel_failure_is_reported_and_drops_the_session(monkeypatch: Any) -> None:
    from eulerlab.broker import angel_check

    monkeypatch.setattr(quotes, "_env", lambda name: "set")
    monkeypatch.setattr(quotes, "_angel_client", object)

    def refuse(*_: Any, **__: Any) -> Any:
        raise angel_check.AngelError("Angel quote refused: rate")

    monkeypatch.setattr(angel_check, "quotes", refuse)
    quotes._angel_session[:] = ["held", 0.0]
    found, error = quotes.from_angel(["SBIN"])
    assert found == {} and "rate" in error
    assert quotes._angel_session[0] is None


def test_angel_rows_become_quotes_with_the_previous_close(monkeypatch: Any) -> None:
    from eulerlab.broker import angel_check

    monkeypatch.setattr(quotes, "_env", lambda name: "set")
    monkeypatch.setattr(quotes, "_angel_client", object)
    monkeypatch.setattr(
        angel_check,
        "quotes",
        lambda symbols, client, **_: {
            "SBIN": {"last_price": 1040.5, "ohlc": {"open": 1030.0, "close": 1016.0}},
            "ZERO": {"last_price": 0, "ohlc": {"close": 5.0}},
        },
    )
    found, error = quotes.from_angel(["SBIN", "ZERO"])
    assert error == "" and set(found) == {"SBIN"}  # a zero is absent, not a -100% day
    assert found["SBIN"].source == "angel"
    assert round(found["SBIN"].change_pct, 2) == 2.41
