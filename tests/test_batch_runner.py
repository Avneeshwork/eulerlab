"""The batch runner and its cache.

The cache is the part worth testing hard. A cache that serves a stale result as
a fresh one is worse than no cache at all — it is a wrong number wearing a
right number's clothes, and nothing downstream can tell.
"""

from __future__ import annotations

from pathlib import Path

from eulerlab.batch import Batch, Item, Outcome, cache_key, read_cached, runner, write_cached


def _compute(calls: list[str]):  # type: ignore[no-untyped-def]
    def inner(item: Item) -> dict[str, object]:
        calls.append(item.strategy_id)
        return {"sharpe": 1.0, "strategy": item.strategy_id}

    return inner


def test_the_key_changes_with_every_input_that_changes_the_answer() -> None:
    base = cache_key("s", {"days": 800})
    assert cache_key("s", {"days": 800}) == base
    assert cache_key("s", {"days": 500}) != base, "a parameter change is a different answer"
    assert cache_key("other", {"days": 800}) != base, "a strategy change is a different answer"


def test_the_key_ignores_dict_ordering() -> None:
    """Same reasoning as the ledger's hash: a harmless refactor must not
    silently empty the cache."""
    assert cache_key("s", {"a": 1, "b": 2}) == cache_key("s", {"b": 2, "a": 1})


def test_a_cache_hit_does_not_recompute(tmp_path: Path) -> None:
    calls: list[str] = []
    item = Item(strategy_id="s", params={"days": 10})
    write_cached(item.key(), {"sharpe": 0.5}, directory=tmp_path)

    result = runner.run([item], _compute(calls), cache_dir=tmp_path)

    assert calls == [], "a cached configuration must not be recomputed"
    assert result.cached == 1
    assert result.computed == 0
    assert result.outcomes[0].result == {"sharpe": 0.5}


def test_a_corrupt_cache_entry_is_a_miss_not_a_failure(tmp_path: Path) -> None:
    """The result can always be recomputed. Refusing to run because a cache
    file is damaged would turn an optimisation into a dependency."""
    (tmp_path / "abc.json").write_text("{not json", encoding="utf-8")
    assert read_cached("abc", directory=tmp_path) is None


def test_one_failure_does_not_kill_the_batch() -> None:
    """One bad configuration in a batch of fifty should not cost the other
    forty-nine — the same rule the universe scan follows for a delisted name."""

    def compute(item: Item) -> dict[str, object]:
        if item.strategy_id == "bad":
            msg = "no panel"
            raise RuntimeError(msg)
        return {"sharpe": 1.0}

    items = [Item("good1"), Item("bad"), Item("good2")]
    result = runner.run(items, compute, use_cache=False)

    assert result.failed == 1
    assert result.computed == 2
    assert "RuntimeError: no panel" in result.outcomes[1].error


def test_unrecorded_counts_the_search_the_ledger_will_never_see() -> None:
    """The honesty number. Screening here is free, and free search is exactly
    what ADR-036 warned gets laundered — so the count is reported rather than
    left to silence."""
    items = [Item(f"s{i}") for i in range(4)]
    result = runner.run(items, lambda _: {"sharpe": 1.0}, use_cache=False)

    summary = runner.summarise(result)
    assert summary["unrecorded"] == 4
    assert summary["spent_trials"] == 0
    assert "the noise bar does not know" in str(summary["note"])


def test_a_fully_cached_batch_reports_no_unrecorded_search() -> None:
    batch = Batch(outcomes=[Outcome(item=Item("s"), cached=True, result={})])
    summary = runner.summarise(batch)
    assert summary["unrecorded"] == 0
    assert "cache" in str(summary["note"])


def test_progress_is_reported_for_every_item() -> None:
    seen: list[tuple[int, int]] = []
    items = [Item("a"), Item("b"), Item("c")]
    runner.run(
        items,
        lambda _: {"x": 1},
        use_cache=False,
        on_progress=lambda i, total, _item: seen.append((i, total)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_run_that_never_traded_is_not_a_zero_result() -> None:
    """Found during development, on my own code.

    `rank_and_hold` over a 250-day window returned Sharpe 0.00 with 0 fills.
    That reads as "no edge"; the truth was that momentum_12_1 declares a
    263-period lookback, so the feature returned None on every symbol and the
    strategy held nothing all run. Same null-versus-zero distinction the fleet
    list depends on, violated one layer down.
    """

    def compute(item: Item) -> dict[str, object]:
        msg = (
            "held nothing for the whole run — 0 fills. rank_and_hold declares a "
            "263-period lookback and the window is 250 days"
        )
        raise RuntimeError(msg)

    result = runner.run([Item("rank_and_hold")], compute, use_cache=False)
    assert result.failed == 1
    assert result.computed == 0
    assert "0 fills" in result.outcomes[0].error
    # It must not be counted as search, because nothing was evaluated.
    assert runner.summarise(result)["unrecorded"] == 0


def test_a_failure_is_never_cached(tmp_path: Path) -> None:
    """The cache must not preserve a wrong answer.

    Also found the hard way: an early bad result was cached, and the fix looked
    like it had not worked because the stale value kept being served — a stale
    result wearing a right number's clothes, which is what the module docstring
    warns about.
    """

    def failing(item: Item) -> dict[str, object]:
        msg = "no panel"
        raise RuntimeError(msg)

    runner.run([Item("s")], failing, cache_dir=tmp_path)
    assert list(tmp_path.glob("*.json")) == [], "a failure must leave no cache entry"
