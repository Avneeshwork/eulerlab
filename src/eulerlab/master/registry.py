"""Time-versioned instrument registry.

Every attribute is stored as an interval, not a current value, so a query with
an ``as_of`` returns what was true *then*. Asking "what was this contract's lot
size in March 2019" must not return today's number, and the only way to
guarantee that is to never store a bare current value in the first place.

Intervals are half-open: ``valid_from <= d < valid_to``, with ``valid_to=None``
meaning still current. Half-open avoids the off-by-one where two intervals both
claim the changeover date.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date

from eulerlab.master.identity import InstrumentId


@dataclass(frozen=True)
class Version[T]:
    """One attribute value, and the window over which it held."""

    value: T
    valid_from: date
    valid_to: date | None = None

    def covers(self, as_of: date) -> bool:
        if as_of < self.valid_from:
            return False
        return self.valid_to is None or as_of < self.valid_to


class History[T]:
    """A sequence of non-overlapping versions of one attribute.

    Built by observation: each observed (date, value) either extends the
    current version or closes it and opens a new one. That is what makes the
    history derivable from daily files rather than from a change log we do not
    have.
    """

    def __init__(self) -> None:
        self._versions: list[Version[T]] = []
        self._starts: list[date] = []

    def observe(self, as_of: date, value: T) -> None:
        """Record that `value` was true on `as_of`.

        Observations must arrive in non-decreasing date order — they come from
        walking daily files forward, and enforcing it here means a caller that
        shuffles input gets an error rather than a silently mangled history.
        """
        if self._versions:
            last = self._versions[-1]
            if as_of < last.valid_from:
                msg = f"observations must not go backwards: {as_of} after {last.valid_from}"
                raise ValueError(msg)
            if last.value == value:
                return  # unchanged; the open interval already covers it
            closed = Version(last.value, last.valid_from, as_of)
            self._versions[-1] = closed
        self._versions.append(Version(value, as_of))
        self._starts.append(as_of)

    def at(self, as_of: date) -> T | None:
        """The value in force on `as_of`, or None if the attribute had none."""
        index = bisect_right(self._starts, as_of) - 1
        if index < 0:
            return None
        version = self._versions[index]
        return version.value if version.covers(as_of) else None

    def versions(self) -> tuple[Version[T], ...]:
        return tuple(self._versions)

    def __len__(self) -> int:
        return len(self._versions)


@dataclass
class Instrument:
    """One issuer's security, with every attribute time-versioned."""

    instrument_id: InstrumentId
    tickers: History[str] = field(default_factory=History)
    isins: History[str] = field(default_factory=History)
    series: History[str] = field(default_factory=History)
    lot_size: History[int] = field(default_factory=History)
    first_seen: date | None = None
    last_seen: date | None = None

    def observe(
        self,
        as_of: date,
        *,
        ticker: str,
        isin: str,
        series: str | None = None,
        lot_size: int | None = None,
    ) -> None:
        self.tickers.observe(as_of, ticker)
        self.isins.observe(as_of, isin)
        if series:
            self.series.observe(as_of, series)
        if lot_size is not None:
            self.lot_size.observe(as_of, lot_size)
        if self.first_seen is None:
            self.first_seen = as_of
        self.last_seen = as_of

    def ticker_at(self, as_of: date) -> str | None:
        return self.tickers.at(as_of)

    def was_traded_on(self, as_of: date) -> bool:
        """Whether this instrument was observed trading on or around `as_of`.

        Bounded by the observation window. A daily file never says "this
        security is delisted" — the rows just stop appearing — so the last
        observation is the only evidence we have of when it ended.
        """
        if self.first_seen is None or self.last_seen is None:
            return False
        return self.first_seen <= as_of <= self.last_seen

    def was_renamed(self) -> bool:
        return len(self.tickers) > 1


class Registry:
    """Every instrument, keyed by internal id."""

    def __init__(self) -> None:
        self._by_id: dict[InstrumentId, Instrument] = {}

    def observe(
        self,
        as_of: date,
        *,
        instrument_id: InstrumentId,
        ticker: str,
        isin: str,
        series: str | None = None,
        lot_size: int | None = None,
    ) -> Instrument:
        instrument = self._by_id.get(instrument_id)
        if instrument is None:
            instrument = Instrument(instrument_id=instrument_id)
            self._by_id[instrument_id] = instrument
        instrument.observe(as_of, ticker=ticker, isin=isin, series=series, lot_size=lot_size)
        return instrument

    def get(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._by_id.get(instrument_id)

    def resolve(self, ticker: str, as_of: date) -> Instrument | None:
        """Find the instrument that traded under `ticker` on `as_of`.

        This is the function that makes tickers usable *safely*: a ticker is
        only ever interpreted with respect to a date, so a reused ticker
        resolves to whichever security actually held it then.

        The observation window matters as much as the ticker history. An
        instrument that stopped trading in 2015 still has an *open* final
        ticker interval, because nothing in a daily file announces a delisting
        — the rows simply stop. Without bounding by `last_seen`, that dead
        instrument keeps claiming its ticker forever and shadows any later
        reuse, silently returning the wrong company.
        """
        for instrument in self._by_id.values():
            if not instrument.was_traded_on(as_of):
                continue
            if instrument.ticker_at(as_of) == ticker:
                return instrument
        return None

    def renamed(self) -> Iterator[Instrument]:
        """Instruments whose ticker changed at least once."""
        return (i for i in self._by_id.values() if i.was_renamed())

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[Instrument]:
        return iter(self._by_id.values())

    def all_ids(self) -> Iterable[InstrumentId]:
        return self._by_id.keys()
