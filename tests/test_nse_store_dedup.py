"""The NSE minute archive has overlapping chunks, and the reader must not.

Three files each cover 2026-06-02 for `NIFTYBEES` — windows of 04-21→06-19,
04-23→06-21 and 05-25→07-23 — so concatenating every overlapping chunk returned
each minute three times: 1,125 rows for a 375-minute session.

Not a cosmetic duplicate. Every indicator here counts bars, so a 60-period mean
covered twenty real minutes, ATR and the volume z-score used a third of their
intended window, and session volume tripled. Any NSE intraday result produced
before this had its lookbacks silently divided by three.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

from eulerlab.intraday import store


def _archive_reachable() -> bool:
    """Whether the B2 minute archive can be read on this machine at all."""
    from eulerlab.env import load_env

    load_env()
    return bool(
        os.environ.get("B2_KEY_ID", "").strip() and os.environ.get("B2_APP_KEY", "").strip()
    )


# Skipped rather than faked when the archive is unreachable.
#
# What these assert is a property of the *real* archive — that its chunks
# overlap and the reader deduplicates them — so a fixture would have to
# recreate the overlap first and would then be testing the fixture. There is
# nothing to check without the thing being checked.
#
# They also cannot simply run and find nothing: `store.fetch` reaches
# `env.require`, which raises `SystemExit` on a missing key. That is right for
# a command and wrong inside a test, and it is why CI reported three hard
# failures on a runner that legitimately has no credentials.
pytestmark = pytest.mark.skipif(
    not _archive_reachable(),
    reason="B2 credentials absent; these read the real NSE minute archive",
)

WINDOW = (dt.date(2026, 6, 1), dt.date(2026, 8, 23))
NSE_SESSION_MINUTES = 375
"""09:15 to 15:30. A full session should return this many bars, not a multiple."""


def test_no_timestamp_appears_twice() -> None:
    candles = store.fetch("NIFTYBEES", start=WINDOW[0], end=WINDOW[1])
    if not candles:  # pragma: no cover - archive unreachable
        return
    stamps = [c.ts for c in candles]
    assert len(stamps) == len(set(stamps))


def test_a_full_session_is_one_session_long() -> None:
    """The tell that caught it: 1,125 is exactly three times 375."""
    import collections

    candles = store.fetch("NIFTYBEES", start=WINDOW[0], end=WINDOW[1])
    if not candles:  # pragma: no cover - archive unreachable
        return
    per_day = collections.Counter(c.ts.date() for c in candles)
    assert max(per_day.values()) <= NSE_SESSION_MINUTES


def test_bars_stay_sorted() -> None:
    candles = store.fetch("NIFTYBEES", start=WINDOW[0], end=WINDOW[1])
    if not candles:  # pragma: no cover - archive unreachable
        return
    assert candles == sorted(candles, key=lambda c: c.ts)
