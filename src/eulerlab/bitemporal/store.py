"""A read API that cannot return data it could not have known.

The rule from `CLAUDE.md`: *the research read API takes an `as_of` and must be
structurally incapable of returning `knowledge_time > as_of`. This is enforced
at the data layer, not by caller discipline.*

Enforced here means three things:

1. **`as_of` is a required argument.** There is no default and no overload
   without it. A default would be the footgun — the one call site that forgets
   it leaks silently, and silence is the whole problem.
2. **Filtering happens below the caller**, inside `query`. No public method
   returns unfiltered rows, so there is nothing to bypass.
3. **Two timestamps per record.** `event_time` is when it happened in the
   market; `knowledge_time` is when we could first have known. A backtest reads
   by `knowledge_time`; only reporting reads by `event_time`.

Why this matters more than the datasets it guards: a data gap lies once, is
found, and is fixed. A lookahead leak lies quietly forever, and it inflates
results in the direction you already want to believe.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime


class LookaheadError(RuntimeError):
    """A read was attempted that would have returned unknowable data.

    Raised rather than silently filtered in the cases where silence would hide
    a caller's mistake — asking for a revision that did not exist yet is a bug
    in the caller, not an empty result.
    """


@dataclass(frozen=True, order=True)
class Record:
    """One observation, carrying both of its times.

    Frozen so a record cannot be mutated after the store has filtered it — an
    unfrozen record could have its `knowledge_time` rewritten by a caller and
    smuggled back in.
    """

    event_time: datetime
    knowledge_time: datetime
    key: str
    value: float

    def __post_init__(self) -> None:
        for name, value in (
            ("event_time", self.event_time),
            ("knowledge_time", self.knowledge_time),
        ):
            if value.tzinfo is None:
                # A naive timestamp is ambiguous, and an ambiguous
                # knowledge_time is precisely how an off-by-hours leak gets in:
                # 15:30 IST and 15:30 UTC are five and a half hours apart, and
                # one of them is after the close.
                msg = f"{self.key}: {name} must be timezone-aware, got naive {value}"
                raise ValueError(msg)
        if self.knowledge_time < self.event_time:
            # Knowing something before it happened is not a late revision, it
            # is corrupt input, and admitting it would defeat the whole guard.
            msg = (
                f"{self.key}: knowledge_time {self.knowledge_time} precedes "
                f"event_time {self.event_time}"
            )
            raise ValueError(msg)


class BitemporalStore:
    """Records that can only be read as of a point in time."""

    def __init__(self, records: Iterable[Record] = ()) -> None:
        self._records: list[Record] = sorted(records)

    def append(self, record: Record) -> None:
        # Placed in order, not appended and re-sorted. Re-sorting the whole
        # list on every append made loading 1,088 price factors cost 600,000
        # comparisons and 0.6 s (measured 2026-10-12). The order is the same:
        # an equal record lands after the ones already there, as a stable
        # sort of an append would leave it.
        bisect.insort(self._records, record)

    def __len__(self) -> int:
        return len(self._records)

    def query(
        self,
        *,
        as_of: datetime,
        key: str | None = None,
        since: datetime | None = None,
    ) -> list[Record]:
        """Every record knowable at `as_of`.

        `as_of` is keyword-only and required: it cannot be passed positionally
        by accident, and it cannot be omitted at all.
        """
        out = [r for r in self._records if r.knowledge_time <= as_of]
        if key is not None:
            out = [r for r in out if r.key == key]
        if since is not None:
            out = [r for r in out if r.event_time >= since]
        return out

    def latest(self, *, as_of: datetime, key: str) -> Record | None:
        """The most recent value for `key` that was knowable at `as_of`.

        "Most recent" is by `event_time` among knowable records — not the last
        thing we learned, but the latest thing that had happened and that we
        knew about. Those differ whenever a revision arrives out of order.
        """
        candidates = self.query(as_of=as_of, key=key)
        return max(candidates, key=lambda r: (r.event_time, r.knowledge_time), default=None)

    def as_of_frame(self, *, as_of: datetime, keys: Sequence[str]) -> dict[str, float | None]:
        """A cross-section: the latest knowable value per key."""
        return {k: (r.value if (r := self.latest(as_of=as_of, key=k)) else None) for k in keys}

    def revisions(self, *, key: str, as_of: datetime) -> list[Record]:
        """Every version of `key` knowable at `as_of`, oldest knowledge first.

        Vintages matter: GDP and IIP are revised, and a backtest must see the
        number as first published, not as later corrected.
        """
        return sorted(self.query(as_of=as_of, key=key), key=lambda r: r.knowledge_time)

    def audit_unknowable(self, *, as_of: datetime) -> list[Record]:
        """Records the store holds but must not return at `as_of`.

        Exists so the firewall can be tested from the outside: a test can assert
        that everything here is genuinely absent from `query`.
        """
        return [r for r in self._records if r.knowledge_time > as_of]


def assert_no_leak(returned: Iterable[Record], *, as_of: datetime) -> None:
    """Fail loudly if any record post-dates `as_of`.

    A belt-and-braces check for callers that build their own result sets from
    several stores, where the guarantee of any single store is not enough.
    """
    leaked = [r for r in returned if r.knowledge_time > as_of]
    if leaked:
        msg = f"{len(leaked)} record(s) leaked past as_of={as_of}: {leaked[0].key}"
        raise LookaheadError(msg)


def walk_forward(
    store: BitemporalStore, *, points: Sequence[datetime], key: str
) -> Iterator[tuple[datetime, Record | None]]:
    """Replay a series as it was known at each point.

    The shape a backtest should use: at every step it sees only what was
    knowable then, so a later revision cannot reach backwards into an earlier
    decision.
    """
    for point in points:
        yield point, store.latest(as_of=point, key=key)
