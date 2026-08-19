"""Adversarial tests: each one *tries* to leak the future.

A test suite that only confirms the happy path proves nothing about a
firewall. Every test below is an attack, named for the attack, and passes only
when the attack fails.

The scenarios are drawn from real cases this project already hit: revisions
arriving late, a symbol renamed after the fact, a corporate action announced
weeks after its effective date, and a bar read before its close printed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from eulerlab.bitemporal.store import (
    BitemporalStore,
    LookaheadError,
    Record,
    assert_no_leak,
    walk_forward,
)

IST = ZoneInfo("Asia/Kolkata")

JAN1 = datetime(2026, 1, 1, 9, 15, tzinfo=IST)
JAN2 = datetime(2026, 1, 2, 9, 15, tzinfo=IST)
JAN3 = datetime(2026, 1, 3, 9, 15, tzinfo=IST)
FEB1 = datetime(2026, 2, 1, 9, 15, tzinfo=IST)


def _store() -> BitemporalStore:
    return BitemporalStore(
        [
            Record(JAN1, JAN1, "CPI", 5.0),
            Record(JAN2, JAN2, "CPI", 5.1),
            # A revision to Jan 1's number, published a month later.
            Record(JAN1, FEB1, "CPI", 4.8),
        ]
    )


# --- attack 1: read a future record directly ---


def test_a_record_published_later_is_not_returned() -> None:
    rows = _store().query(as_of=JAN2)
    assert all(r.knowledge_time <= JAN2 for r in rows)
    assert 4.8 not in [r.value for r in rows]


def test_the_store_holds_the_future_record_it_refuses_to_return() -> None:
    """Proves the filter is doing work, not that the data is simply absent."""
    store = _store()
    assert len(store.audit_unknowable(as_of=JAN2)) == 1
    assert len(store) == 3


# --- attack 2: the revision reaching backwards ---


def test_a_later_revision_does_not_rewrite_the_past() -> None:
    """The classic macro leak: February's corrected CPI used in January."""
    store = _store()
    on_jan2 = store.latest(as_of=JAN2, key="CPI")
    assert on_jan2 is not None
    assert on_jan2.value == 5.1  # what was known then


def test_the_revision_is_visible_once_it_exists() -> None:
    store = _store()
    after = store.revisions(key="CPI", as_of=FEB1)
    assert len(after) == 3
    assert after[-1].value == 4.8


# --- attack 3: walking forward must not see ahead ---


def test_a_walk_forward_never_sees_a_later_revision() -> None:
    store = _store()
    seen = {
        point: (rec.value if rec else None)
        for point, rec in walk_forward(store, points=[JAN1, JAN2, JAN3], key="CPI")
    }
    assert seen[JAN1] == 5.0
    assert seen[JAN2] == 5.1
    assert seen[JAN3] == 5.1  # NOT 4.8 — that is not knowable until February


# --- attack 4: corrupt input claiming impossible knowledge ---


def test_knowing_something_before_it_happened_is_rejected() -> None:
    with pytest.raises(ValueError, match="precedes"):
        Record(FEB1, JAN1, "CPI", 5.0)


def test_a_record_cannot_be_mutated_after_filtering() -> None:
    """An unfrozen record could have its knowledge_time rewritten and smuggled
    back into a result set."""
    rec = Record(JAN1, JAN1, "CPI", 5.0)
    with pytest.raises(AttributeError):
        rec.knowledge_time = FEB1  # type: ignore[misc]


# --- attack 5: bypassing the as_of ---


def test_as_of_cannot_be_passed_positionally() -> None:
    """Keyword-only, so it cannot be supplied by accident in the wrong slot."""
    with pytest.raises(TypeError):
        _store().query(JAN2)  # type: ignore[call-arg]


def test_there_is_no_read_method_without_as_of() -> None:
    """Structural: every public reader requires as_of.

    If a method ever appears that returns records without one, this fails —
    which is the point. Convention would not survive a refactor.
    """
    import inspect

    from eulerlab.bitemporal import store as module

    readers = ("query", "latest", "as_of_frame", "revisions", "audit_unknowable")
    for name in readers:
        sig = inspect.signature(getattr(module.BitemporalStore, name))
        param = sig.parameters.get("as_of")
        assert param is not None, f"{name} has no as_of"
        assert param.default is inspect.Parameter.empty, f"{name} defaults as_of"
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} allows positional as_of"


# --- attack 6: a cross-section pulling one future value ---


def test_a_cross_section_cannot_include_a_future_value() -> None:
    store = BitemporalStore(
        [
            Record(JAN1, JAN1, "A", 1.0),
            Record(JAN1, FEB1, "B", 2.0),  # B is not knowable in January
        ]
    )
    frame = store.as_of_frame(as_of=JAN2, keys=["A", "B"])
    assert frame == {"A": 1.0, "B": None}


# --- attack 7: assembling results outside the store ---


def test_a_hand_assembled_result_set_is_still_caught() -> None:
    """Callers combining several stores lose the per-store guarantee."""
    rows = [Record(JAN1, JAN1, "A", 1.0), Record(JAN1, FEB1, "B", 2.0)]
    with pytest.raises(LookaheadError, match="leaked past"):
        assert_no_leak(rows, as_of=JAN2)


def test_a_clean_result_set_passes_the_belt_and_braces_check() -> None:
    assert_no_leak(_store().query(as_of=JAN2), as_of=JAN2)


# --- attack 8: boundary conditions ---


def test_a_record_known_exactly_at_as_of_is_included() -> None:
    """Half-open the other way would silently drop the current bar."""
    assert len(_store().query(as_of=JAN1)) == 1


def test_a_record_known_one_microsecond_later_is_excluded() -> None:
    store = _store()
    assert len(store.query(as_of=JAN1 - timedelta(microseconds=1))) == 0


def test_an_empty_store_returns_nothing_rather_than_failing() -> None:
    assert BitemporalStore().query(as_of=JAN2) == []
    assert BitemporalStore().latest(as_of=JAN2, key="X") is None


# --- attack 9: the symbol-rename leak this project actually hit ---


def test_a_ticker_adopted_later_is_not_knowable_earlier() -> None:
    """ZOMATO became ETERNAL in 2025. A 2023 query must not see ETERNAL."""
    store = BitemporalStore(
        [
            Record(JAN1, JAN1, "ZOMATO", 100.0),
            Record(FEB1, FEB1, "ETERNAL", 120.0),
        ]
    )
    known = {r.key for r in store.query(as_of=JAN2)}
    assert known == {"ZOMATO"}


# --- attack 10: an ambiguous timestamp ---


def test_a_naive_timestamp_is_rejected() -> None:
    """15:30 IST and 15:30 UTC are five and a half hours apart, and one of them
    is after the close. An ambiguous knowledge_time is a leak waiting to
    happen, so the store refuses it rather than guessing a zone."""
    naive = datetime(2026, 1, 1, 9, 15)  # noqa: DTZ001 - deliberately naive
    with pytest.raises(ValueError, match="timezone-aware"):
        Record(naive, naive, "CPI", 5.0)
