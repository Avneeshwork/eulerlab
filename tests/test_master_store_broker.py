"""Persisted master round-trips, and the broker map compares like with like."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.master.broker_map import (
    bare_ticker,
    build_mapping,
    detect_token_reuse,
    is_equity_symbol,
)
from eulerlab.master.identity import InstrumentId
from eulerlab.master.registry import Registry
from eulerlab.master.store import BuildStamp, load, save

ZOMATO = InstrumentId.from_isin("INE758T01015")


def _registry() -> Registry:
    r = Registry()
    for m in range(1, 13):
        r.observe(
            date(2023, m, 1),
            instrument_id=ZOMATO,
            ticker="ZOMATO",
            isin="INE758T01015",
            lot_size=50,
        )
    for m in range(1, 9):
        r.observe(
            date(2026, m, 1),
            instrument_id=ZOMATO,
            ticker="ETERNAL",
            isin="INE758T01015",
            lot_size=65,
        )
    return r


def _stamp() -> BuildStamp:
    return BuildStamp.now(source_files=2, first_date=date(2023, 1, 1), last_date=date(2026, 8, 1))


def test_a_saved_master_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    save(_registry(), _stamp(), path)
    loaded, stamp = load(path)
    assert len(loaded) == 1
    assert stamp.source_files == 2


def test_the_rename_survives_a_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    save(_registry(), _stamp(), path)
    loaded, _ = load(path)
    assert loaded.resolve("ZOMATO", date(2023, 6, 1)) is not None
    assert loaded.resolve("ETERNAL", date(2026, 6, 1)) is not None


def test_a_round_trip_does_not_introduce_lookahead(tmp_path: Path) -> None:
    """The reloaded master must not answer a future name on a past date."""
    path = tmp_path / "m.json"
    save(_registry(), _stamp(), path)
    loaded, _ = load(path)
    assert loaded.resolve("ETERNAL", date(2023, 6, 1)) is None


def test_lot_size_history_survives_a_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    save(_registry(), _stamp(), path)
    loaded, _ = load(path)
    inst = loaded.get(ZOMATO)
    assert inst is not None
    assert inst.lot_size.at(date(2023, 6, 1)) == 50
    assert inst.lot_size.at(date(2026, 6, 1)) == 65


def test_saving_twice_is_byte_identical(tmp_path: Path) -> None:
    """Determinism: a diff should mean a real change, not dict ordering."""
    stamp = _stamp()
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save(_registry(), stamp, a)
    save(_registry(), stamp, b)
    assert a.read_bytes() == b.read_bytes()


def test_a_wrong_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    save(_registry(), _stamp(), path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"schema_version": 1', '"schema_version": 99'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema"):
        load(path)


# --- broker mapping ---


@pytest.mark.parametrize("symbol", ["0IRFC35-N0", "0ABCL31-N0", "SOMETHING-N0", "ABSLLQINAV"])
def test_bonds_and_nav_feeds_are_not_equities(symbol: str) -> None:
    """Kite files bonds and ETF NAV feeds under instrument_type EQ.

    Counting them as unmapped produced 7,485 false failures, which reads as a
    broken master rather than a scope mismatch. A check that cries wolf is
    ignored.
    """
    assert not is_equity_symbol(symbol)


@pytest.mark.parametrize("symbol", ["RELIANCE", "RELINFRA-BE", "TCS"])
def test_real_equities_are_recognised(symbol: str) -> None:
    assert is_equity_symbol(symbol)


def test_a_series_suffix_is_stripped_for_matching() -> None:
    assert bare_ticker("RELINFRA-BE") == "RELINFRA"
    assert bare_ticker("RELIANCE") == "RELIANCE"


def test_mapping_links_a_known_instrument() -> None:
    report = build_mapping(_registry(), {"ETERNAL": 12345}, as_of=date(2026, 6, 1))
    assert report.ok
    assert report.linked[0].instrument_id == ZOMATO
    assert report.linked[0].token == 12345


def test_an_unresolvable_symbol_is_reported_not_dropped() -> None:
    report = build_mapping(_registry(), {"NOSUCHCO": 999}, as_of=date(2026, 6, 1))
    assert not report.ok
    assert report.unmapped == ["NOSUCHCO"]


def test_non_equities_are_skipped_not_counted_as_failures() -> None:
    report = build_mapping(_registry(), {"0IRFC35-N0": 1, "ETERNAL": 2}, as_of=date(2026, 6, 1))
    assert report.skipped_non_equity == 1
    assert report.ok


def test_token_reuse_across_instruments_is_detected() -> None:
    """Kite documents that tokens are reused after expiry."""
    other = InstrumentId.from_isin("INE111A01011")
    r = _registry()
    for m in range(1, 9):
        r.observe(date(2026, m, 1), instrument_id=other, ticker="OTHER", isin="INE111A01011")
    report = build_mapping(r, {"ETERNAL": 500, "OTHER": 500}, as_of=date(2026, 6, 1))
    assert len(detect_token_reuse(report.linked)) == 1
