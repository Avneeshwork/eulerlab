"""Combinatorial purged cross-validation.

Ordinary k-fold cross-validation is invalid on financial time series, and the
reason is specific rather than vague hand-waving about "temporal structure".

A label here is a **forward return**: the label attached to day *t* is built
from prices over *t* to *t+h*. So a training sample at day *t* and a test
sample at day *t+1* share almost all of their outcome window. Put one in train
and the other in test and the model has already been shown most of the answer
it is about to be scored on. The measured out-of-sample performance is then
partly in-sample, and it is optimistic in a way no amount of extra folds
fixes — more folds makes it worse, because more boundaries means more overlap.

Two corrections, and both are needed:

**Purging** removes training samples whose label window overlaps the test
window at all. That is the leak above, removed directly.

**Embargo** removes a further stretch of training data immediately *after*
each test block. Purging alone is not enough because financial series are
serially correlated: the days right after a test block are informative about
it even when their label windows do not literally overlap. The embargo is a
blunt instrument for a real effect, and leaving it out is the more common
mistake of the two.

**Combinatorial** means testing on every combination of *k* blocks out of *N*
rather than one block at a time. That yields many backtest paths from one
history instead of a single one, which is what makes the probability of
backtest overfitting estimable at all — with one path there is nothing to
compare a "best" configuration against.

Reference: López de Prado, *Advances in Financial Machine Learning*, ch. 7 and
12. The construction here follows that treatment; nothing in it is original
and it should not be, because the value is in it being the standard method
rather than one I invented.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations


@dataclass(frozen=True)
class Split:
    """One train/test division, already purged and embargoed."""

    test_days: tuple[date, ...]
    train_days: tuple[date, ...]
    purged: int
    embargoed: int

    @property
    def n_test(self) -> int:
        return len(self.test_days)

    @property
    def n_train(self) -> int:
        return len(self.train_days)


def blocks(days: Sequence[date], n_blocks: int) -> list[tuple[date, ...]]:
    """Split a timeline into contiguous, roughly equal blocks.

    Contiguous rather than interleaved: a block must be a stretch of calendar
    time for purging and embargo to mean anything at all.
    """
    if n_blocks < 2:
        msg = f"need at least 2 blocks to cross-validate, got {n_blocks}"
        raise ValueError(msg)
    if len(days) < n_blocks:
        msg = f"{len(days)} days cannot be split into {n_blocks} blocks"
        raise ValueError(msg)
    size, extra = divmod(len(days), n_blocks)
    out: list[tuple[date, ...]] = []
    start = 0
    for i in range(n_blocks):
        length = size + (1 if i < extra else 0)
        out.append(tuple(days[start : start + length]))
        start += length
    return out


def split(
    days: Sequence[date],
    test_blocks: Sequence[tuple[date, ...]],
    *,
    horizon: int,
    embargo: int,
) -> Split:
    """Build one purged, embargoed split.

    `horizon` is the label's forward window in trading days — the same number
    the IC harness and the backtester use. It must be passed rather than
    guessed, because purging the wrong width is worse than not purging: it
    looks rigorous and leaks anyway.
    """
    ordinal = {day: i for i, day in enumerate(days)}
    test_set = {day for block in test_blocks for day in block}
    test_indices = sorted(ordinal[d] for d in test_set)

    purged_indices: set[int] = set()
    embargoed_indices: set[int] = set()

    for block in test_blocks:
        first = ordinal[block[0]]
        last = ordinal[block[-1]]
        # Purge: any training day whose label window (i .. i+horizon) reaches
        # into this test block.
        for i in range(max(0, first - horizon), first):
            purged_indices.add(i)
        # Embargo: a gap after the block, for serial correlation that purging
        # does not catch.
        for i in range(last + 1, min(len(days), last + 1 + embargo)):
            embargoed_indices.add(i)

    excluded = set(test_indices) | purged_indices | embargoed_indices
    train_days = tuple(days[i] for i in range(len(days)) if i not in excluded)

    return Split(
        test_days=tuple(sorted(test_set)),
        train_days=train_days,
        purged=len(purged_indices - set(test_indices)),
        embargoed=len(embargoed_indices - set(test_indices) - purged_indices),
    )


def cpcv_splits(
    days: Sequence[date],
    *,
    n_blocks: int = 6,
    test_block_count: int = 2,
    horizon: int = 21,
    embargo: int = 5,
) -> Iterator[Split]:
    """Every combination of `test_block_count` blocks out of `n_blocks`.

    Defaults of 6 choose 2 give 15 paths. That is deliberately modest: the
    count grows combinatorially and each path costs a full backtest, so a
    larger grid buys precision in the PBO estimate at a cost that rises fast.
    """
    all_blocks = blocks(days, n_blocks)
    for chosen in combinations(range(n_blocks), test_block_count):
        yield split(
            days,
            [all_blocks[i] for i in chosen],
            horizon=horizon,
            embargo=embargo,
        )


def leakage_check(split_: Split, days: Sequence[date], *, horizon: int) -> str | None:
    """Confirm no training day's label window reaches into the test set.

    The property purging exists to guarantee, asserted rather than assumed.
    Returns a description of the first violation, or None when clean — a
    silent bool would make a failure easy to skip past.

    **`days` must be the full original timeline**, and that argument is the
    whole point of this function's signature. The first version derived its
    ordering from `train_days | test_days`, which is the timeline *after*
    purging has removed the days in between — so two dates 42 trading days
    apart appeared adjacent and the check reported leakage on 14 of 15
    correctly-purged paths. A label window is measured in real elapsed
    sessions, so it can only be checked against the real calendar.
    """
    test_set = set(split_.test_days)
    if not test_set:
        return None
    ordinal = {day: i for i, day in enumerate(days)}
    test_indices = {ordinal[d] for d in test_set if d in ordinal}

    for day in split_.train_days:
        i = ordinal.get(day)
        if i is None:
            continue
        for j in range(i + 1, min(len(days), i + horizon + 1)):
            if j in test_indices:
                return (
                    f"training day {day} has a {horizon}-day label window reaching "
                    f"into test day {days[j]}"
                )
    return None
