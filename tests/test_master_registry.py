"""The registry must answer with what was true then, never what is true now."""

from __future__ import annotations

from datetime import date

import pytest

from eulerlab.master.identity import InstrumentId
from eulerlab.master.registry import History, Registry

ZOMATO = InstrumentId.from_isin("INE758T01015")


def test_a_value_is_returned_for_the_date_it_held() -> None:
    h: History[int] = History()
    h.observe(date(2023, 1, 2), 50)
    h.observe(date(2024, 11, 20), 75)
    h.observe(date(2026, 1, 1), 65)

    assert h.at(date(2023, 6, 1)) == 50
    assert h.at(date(2025, 3, 1)) == 75
    assert h.at(date(2026, 8, 1)) == 65


def test_a_date_before_the_first_observation_has_no_value() -> None:
    h: History[int] = History()
    h.observe(date(2023, 1, 2), 50)
    assert h.at(date(2022, 12, 31)) is None


def test_unchanged_observations_do_not_create_versions() -> None:
    h: History[int] = History()
    for day in range(1, 20):
        h.observe(date(2023, 1, day), 50)
    assert len(h) == 1


def test_intervals_are_half_open_so_the_changeover_date_is_unambiguous() -> None:
    h: History[int] = History()
    h.observe(date(2023, 1, 2), 50)
    h.observe(date(2024, 11, 20), 75)
    # The new value owns the changeover date; the old one does not.
    assert h.at(date(2024, 11, 19)) == 50
    assert h.at(date(2024, 11, 20)) == 75


def test_observations_may_not_go_backwards() -> None:
    h: History[int] = History()
    h.observe(date(2024, 1, 1), 50)
    with pytest.raises(ValueError, match="backwards"):
        h.observe(date(2023, 1, 1), 60)


# --- the rename case, end to end ---


def _zomato_registry() -> Registry:
    r = Registry()
    r.observe(date(2023, 6, 15), instrument_id=ZOMATO, ticker="ZOMATO", isin="INE758T01015")
    r.observe(date(2026, 8, 14), instrument_id=ZOMATO, ticker="ETERNAL", isin="INE758T01015")
    return r


def test_a_renamed_instrument_resolves_under_the_name_it_had_then() -> None:
    r = _zomato_registry()
    assert r.resolve("ZOMATO", date(2023, 6, 15)) is not None
    assert r.resolve("ETERNAL", date(2026, 8, 14)) is not None


def test_a_ticker_does_not_resolve_before_it_was_adopted() -> None:
    """Asking for ETERNAL in 2023 must return nothing, not today's instrument."""
    assert _zomato_registry().resolve("ETERNAL", date(2023, 6, 15)) is None


def test_both_names_are_the_same_instrument() -> None:
    r = _zomato_registry()
    assert r.resolve("ZOMATO", date(2023, 6, 15)) is r.resolve("ETERNAL", date(2026, 8, 14))
    assert len(r) == 1


def test_renames_are_discoverable() -> None:
    r = _zomato_registry()
    renamed = list(r.renamed())
    assert len(renamed) == 1
    assert renamed[0].ticker_at(date(2023, 6, 15)) == "ZOMATO"
    assert renamed[0].ticker_at(date(2026, 8, 14)) == "ETERNAL"


def test_a_reused_ticker_resolves_to_the_right_security() -> None:
    """The nastier case: the same ticker held by two different issuers.

    Each instrument is observed over a span, as it would be when walking daily
    files — a security appears in every day's bhavcopy while it trades.
    """
    r = Registry()
    first = InstrumentId.from_isin("INE111A01011")
    second = InstrumentId.from_isin("INE222B01012")
    for month in range(1, 13):  # first trades through 2015
        r.observe(date(2015, month, 1), instrument_id=first, ticker="SAME", isin="INE111A01011")
    for month in range(1, 9):  # second picks up the ticker in 2026
        r.observe(date(2026, month, 1), instrument_id=second, ticker="SAME", isin="INE222B01012")

    got_2015 = r.resolve("SAME", date(2015, 6, 1))
    got_2026 = r.resolve("SAME", date(2026, 6, 1))
    assert got_2015 is not None and got_2015.instrument_id == first
    assert got_2026 is not None and got_2026.instrument_id == second


def test_a_delisted_instrument_stops_claiming_its_ticker() -> None:
    """A daily file never announces a delisting - the rows just stop.

    Without bounding by the observation window, this instrument would still
    answer to SAME in 2026 and shadow whoever holds it then.
    """
    r = Registry()
    dead = InstrumentId.from_isin("INE111A01011")
    for month in range(1, 13):
        r.observe(date(2015, month, 1), instrument_id=dead, ticker="SAME", isin="INE111A01011")

    assert r.resolve("SAME", date(2015, 6, 1)) is not None
    assert r.resolve("SAME", date(2020, 6, 1)) is None


def test_lot_size_is_answered_as_of_a_past_date() -> None:
    r = Registry()
    nifty = InstrumentId.from_isin("INE999Z01011")
    r.observe(date(2023, 1, 2), instrument_id=nifty, ticker="X", isin="INE999Z01011", lot_size=50)
    r.observe(date(2024, 11, 20), instrument_id=nifty, ticker="X", isin="INE999Z01011", lot_size=75)

    instrument = r.get(nifty)
    assert instrument is not None
    assert instrument.lot_size.at(date(2024, 1, 1)) == 50
    assert instrument.lot_size.at(date(2025, 1, 1)) == 75
