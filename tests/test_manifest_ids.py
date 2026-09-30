"""The manifest records leaf names for the one tree that cannot recover them.

Every other landed tree keeps a directory per symbol, which survives a prune and
answers "which symbols exist" from disk for free. Fund history is flat —
`mf/history/119551.jsonl.gz` — so pruning leaves nothing behind and the bucket
was the only source: 14,280 keys and 18.7 seconds, paid by the instrument picker.
"""

from __future__ import annotations

from eulerlab.ingest import manifest


def test_only_the_tree_that_needs_ids_records_them() -> None:
    """Recording every tree's leaf names would bloat the census for no reader.

    `us/minute` alone is 15,952 keys. The set is deliberately small and this
    pins it, so adding a tree to it is a decision rather than a habit.
    """
    assert {"mf"} == manifest.ID_TREES


def test_the_key_matches_what_TREES_calls_it() -> None:
    """`"mf"`, not `"mf/history"` — which is what its pattern suggests.

    Written wrong the first time. A tree name that does not match what the
    manifest records reads as "no such tree" and falls silently through to a
    bucket enumeration; that mistake has now happened three times in this
    codebase (ADR-046), which is why it is asserted rather than assumed.
    """
    keys = {key for key, _tree, _pattern in manifest.TREES}
    assert keys >= manifest.ID_TREES


def test_recorded_ids_round_trip_through_the_file() -> None:
    census = manifest.TreeCensus(files=2, groups=0, newest="b.jsonl.gz", ids=("a", "b"))
    assert census.to_row()["ids"] == ["a", "b"]


def test_a_tree_without_ids_does_not_carry_an_empty_field() -> None:
    """Absent rather than empty, so the file does not grow a column of `[]`."""
    census = manifest.TreeCensus(files=2, groups=1, newest="x.jsonl.gz")
    assert "ids" not in census.to_row()
