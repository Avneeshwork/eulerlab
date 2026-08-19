"""Calendar from evidence, and the contract registry's point-in-time answers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from eulerlab.master.calendar import DayKind, TradingCalendar
from eulerlab.master.contracts import ContractRegistry
from eulerlab.master.derivatives import ContractId, ContractType, Right


def _cal(pairs: list[tuple[date, str]]) -> TradingCalendar:
    return TradingCalendar.from_observations(pairs)


def test_a_day_with_both_segments_is_a_trading_day() -> None:
    c = _cal([(date(2026, 8, 14), "cm"), (date(2026, 8, 14), "fo")])
    assert c.classify(date(2026, 8, 14)).kind is DayKind.TRADING


def test_a_weekday_with_no_file_is_closed_not_trading() -> None:
    c = _cal([(date(2026, 8, 14), "cm"), (date(2026, 8, 14), "fo")])
    assert c.classify(date(2026, 8, 13)).kind is DayKind.CLOSED
    assert not c.is_trading_day(date(2026, 8, 13))


def test_one_segment_only_is_suspect_not_assumed() -> None:
    """A real closure shuts both segments. One means holiday or missing file,
    and guessing either way hides the other."""
    c = _cal([(date(2021, 3, 30), "cm")])
    assert c.classify(date(2021, 3, 30)).kind is DayKind.SUSPECT
    assert [d.day for d in c.suspect_days()] == [date(2021, 3, 30)]


def test_a_weekend_session_is_recorded_as_trading() -> None:
    """A weekday rule would silently miss a Muhurat session."""
    saturday = date(2026, 8, 15)
    c = _cal([(saturday, "cm"), (saturday, "fo")])
    assert c.classify(saturday).kind is DayKind.TRADING
    assert c.sessions_on_weekends() == [saturday]


def test_a_weekend_with_no_file_is_weekend() -> None:
    c = _cal([(date(2026, 8, 14), "cm"), (date(2026, 8, 14), "fo")])
    assert c.classify(date(2026, 8, 15)).kind is DayKind.WEEKEND


def test_neighbouring_trading_days_skip_closures() -> None:
    c = _cal([(date(2026, 8, 14), "cm"), (date(2026, 8, 17), "cm")])
    assert c.previous_trading_day(date(2026, 8, 17)) == date(2026, 8, 14)
    assert c.next_trading_day(date(2026, 8, 14)) == date(2026, 8, 17)
    assert c.next_trading_day(date(2026, 8, 17)) is None


def test_long_gaps_are_reported() -> None:
    c = _cal([(date(2026, 1, 1), "cm"), (date(2026, 3, 1), "cm")])
    assert list(c.gaps_longer_than(5)) == [(date(2026, 1, 1), date(2026, 3, 1))]


# --- contract registry ---


NIFTY_FUT = ContractId("NIFTY", date(2026, 8, 25), ContractType.FUTURE)


def test_lot_size_is_answered_as_of_a_past_date() -> None:
    """The Sprint 3 acceptance question, and the reason lot size is versioned.

    Measured from our own bhavcopy: NIFTY was 50 in Mar 2024, 25 in Nov 2024,
    75 in Mar 2025 and 65 by Mar 2026. A hardcoded value is wrong for most of
    that span.
    """
    r = ContractRegistry()
    for day, lot in [
        (date(2024, 3, 1), 50),
        (date(2024, 11, 1), 25),
        (date(2025, 3, 1), 75),
        (date(2026, 3, 1), 65),
    ]:
        r.observe(day, NIFTY_FUT, lot_size=lot)

    assert r.lot_size_at(NIFTY_FUT, date(2024, 6, 1)) == 50
    assert r.lot_size_at(NIFTY_FUT, date(2024, 12, 1)) == 25
    assert r.lot_size_at(NIFTY_FUT, date(2025, 6, 1)) == 75
    assert r.lot_size_at(NIFTY_FUT, date(2026, 6, 1)) == 65


def test_a_date_before_the_contract_existed_has_no_lot_size() -> None:
    r = ContractRegistry()
    r.observe(date(2024, 3, 1), NIFTY_FUT, lot_size=50)
    assert r.lot_size_at(NIFTY_FUT, date(2023, 1, 1)) is None


def test_lot_size_changes_are_detectable() -> None:
    r = ContractRegistry()
    r.observe(date(2024, 3, 1), NIFTY_FUT, lot_size=50)
    r.observe(date(2024, 11, 1), NIFTY_FUT, lot_size=25)
    contract = r.get(NIFTY_FUT)
    assert contract is not None and contract.lot_size_changed


def test_an_option_needs_a_strike_and_a_right() -> None:
    with pytest.raises(ValueError, match="needs a strike"):
        ContractId("NIFTY", date(2026, 8, 25), ContractType.OPTION)


def test_a_future_may_not_carry_a_strike() -> None:
    with pytest.raises(ValueError, match="no strike"):
        ContractId("NIFTY", date(2026, 8, 25), ContractType.FUTURE, Decimal("100"), Right.CALL)


def test_options_differing_only_by_right_are_different_contracts() -> None:
    call = ContractId("NIFTY", date(2026, 8, 25), ContractType.OPTION, Decimal("25000"), Right.CALL)
    put = ContractId("NIFTY", date(2026, 8, 25), ContractType.OPTION, Decimal("25000"), Right.PUT)
    assert call != put


def test_a_contract_stops_being_live_after_expiry() -> None:
    r = ContractRegistry()
    r.observe(date(2026, 8, 1), NIFTY_FUT, lot_size=65)
    r.observe(date(2026, 8, 25), NIFTY_FUT, lot_size=65)
    assert list(r.live_on(date(2026, 8, 10)))
    assert not list(r.live_on(date(2026, 9, 10)))
