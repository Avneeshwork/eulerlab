"""Priming the listing cache must answer exactly as the network would."""

from __future__ import annotations

import pytest

from eulerlab.ingest import landing_reader


def test_priming_matches_what_a_real_listing_would_have_found() -> None:
    """The primed answer and the fetched answer come from one `_matches`.

    They are two ways of reaching the same set, and a divergence would be
    invisible: the census would simply report the wrong counts, confidently.
    """
    prefix = "eulerlab/"
    keys = [
        f"{prefix}us/bars/QQQ/2026-08-01.jsonl.gz",
        f"{prefix}us/bars/SPY/2026-08-01.jsonl.gz",
        f"{prefix}us/minute/QQQ/2026-08-01.jsonl.gz",
        f"{prefix}us/sp500/2026-08-01.jsonl.gz",
        f"{prefix}fx/EURUSD/2026/w31.jsonl.gz",
        f"{prefix}mf/history/119551.jsonl.gz",
        f"{prefix}mf/enriched/2026-08-01.jsonl.gz",
        f"{prefix}crypto/BTCUSDT/2026-08-01.jsonl.gz",
        f"{prefix}calendar/2026-08-01.jsonl.gz",
        "elsewhere/us/bars/QQQ/nope.jsonl.gz",  # outside the prefix
    ]
    wanted = [
        ("us", "bars/*/*.jsonl.gz"),
        ("us", "minute/*/*.jsonl.gz"),
        ("us", "sp500/*.jsonl.gz"),
        ("fx", "*/*/*.jsonl.gz"),
        ("mf", "history/*.jsonl.gz"),
        ("mf", "enriched/*.jsonl.gz"),
        ("crypto", "*/*.jsonl.gz"),
        ("calendar", "*.jsonl.gz"),
    ]

    filled = landing_reader.prime_listing(keys, prefix, wanted)
    assert filled == len(wanted)

    relatives = [k[len(prefix) :] for k in keys if k.startswith(prefix)]
    for tree, pattern in wanted:
        primed = landing_reader._LISTED[(tree, pattern)][1]
        expected = tuple(sorted(r for r in relatives if landing_reader._matches(r, tree, pattern)))
        assert primed == expected, f"{tree}/{pattern} primed differently"

    # The patterns must actually discriminate, or the test proves nothing.
    assert landing_reader._LISTED[("us", "bars/*/*.jsonl.gz")][1] == (
        "us/bars/QQQ/2026-08-01.jsonl.gz",
        "us/bars/SPY/2026-08-01.jsonl.gz",
    )
    assert landing_reader._LISTED[("mf", "history/*.jsonl.gz")][1] == (
        "mf/history/119551.jsonl.gz",
    )


def test_priming_ignores_keys_outside_the_prefix() -> None:
    prefix = "eulerlab/"
    landing_reader.prime_listing(
        ["other-bucket-root/calendar/2026-08-01.jsonl.gz"], prefix, [("calendar", "*.jsonl.gz")]
    )
    assert landing_reader._LISTED[("calendar", "*.jsonl.gz")][1] == ()


def test_a_primed_entry_is_served_instead_of_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`available` must read the primed value rather than call the store."""

    def explode(*_: object, **__: object) -> None:
        raise AssertionError("the network was used despite a primed listing")

    prefix = "eulerlab/"
    landing_reader.prime_listing(
        [f"{prefix}calendar/2026-08-01.jsonl.gz"], prefix, [("calendar", "*.jsonl.gz")]
    )
    monkeypatch.setattr(landing_reader, "_store_and_prefix", explode)
    monkeypatch.setattr(landing_reader, "cloud_enabled", lambda: True)

    assert "calendar/2026-08-01.jsonl.gz" in landing_reader.available("calendar", "*.jsonl.gz")


def test_priming_must_include_what_the_run_uploaded() -> None:
    """A listing taken before the uploads describes the wrong bucket.

    The census counts local files and remote ones together, so today a file
    uploaded this run is still counted — it is on disk. That stops being true
    the moment anything prunes local files between the sync and the census,
    which is exactly what `make daily` does. It survives only because those
    are separate processes and the cache does not cross; this pins the union
    so the guarantee does not rest on that.
    """
    prefix = "eulerlab/"
    before = [f"{prefix}calendar/2026-08-01.jsonl.gz"]
    uploaded = [f"{prefix}calendar/2026-08-27.jsonl.gz"]

    landing_reader.prime_listing(before, prefix, [("calendar", "*.jsonl.gz")])
    stale = landing_reader._LISTED[("calendar", "*.jsonl.gz")][1]
    assert "calendar/2026-08-27.jsonl.gz" not in stale, "the pre-upload listing cannot know it"

    landing_reader.prime_listing([*before, *uploaded], prefix, [("calendar", "*.jsonl.gz")])
    fresh = landing_reader._LISTED[("calendar", "*.jsonl.gz")][1]
    assert fresh == ("calendar/2026-08-01.jsonl.gz", "calendar/2026-08-27.jsonl.gz")


def test_priming_replaces_rather_than_accumulates() -> None:
    """A second prime must not leave the first one's keys behind."""
    prefix = "eulerlab/"
    landing_reader.prime_listing(
        [f"{prefix}calendar/one.jsonl.gz"], prefix, [("calendar", "*.jsonl.gz")]
    )
    landing_reader.prime_listing(
        [f"{prefix}calendar/two.jsonl.gz"], prefix, [("calendar", "*.jsonl.gz")]
    )
    assert landing_reader._LISTED[("calendar", "*.jsonl.gz")][1] == ("calendar/two.jsonl.gz",)
