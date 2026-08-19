"""Map internal instrument ids to broker tokens, and detect drift.

The playbook is blunt about this: a daily reconciliation that alerts on any
unmapped instrument "will save you more money than any alpha". The failure it
prevents is placing an order against the wrong token.

Two properties make this harder than a dictionary:

* **Broker tokens are reused.** Kite's own documentation says exchanges reuse
  instrument tokens for different derivatives after expiry, so a token is only
  meaningful together with a date.
* **Kite decorates tickers with the series.** A stock in the trade-for-trade
  segment is `RELINFRA-BE` there and `RELINFRA` in the bhavcopy. Matching the
  bare name missed four instruments and reported them as delisted — a false
  negative that looked exactly like a corporate event.

So the mapping is built by resolving the broker's ticker *as of a date* through
the security master, and anything that fails to resolve is reported rather than
dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from eulerlab.master.identity import InstrumentId
from eulerlab.master.registry import Registry

SERIES_SUFFIXES = ("-BE", "-BZ", "-SM", "-ST", "-IT")

DEBT_SUFFIX = re.compile(r"-N[0-9A-Z]$")


def is_equity_symbol(tradingsymbol: str) -> bool:
    """Whether a Kite `EQ` row is actually a company equity.

    Kite files bonds and debentures under `instrument_type == "EQ"` too.
    Measured on the live list: of 10,185 NSE "EQ" rows, **5,991 begin with a
    digit** (a debt convention such as `0IRFC35-N0`) and a further 115 carry an
    `-Nx` debt series suffix. Only ~4,000 are company shares.

    Without this filter the mapping reported 7,485 "unmapped instruments",
    which reads as a broken master rather than what it was: comparing an equity
    master against a list that is mostly bonds. A check that cries wolf gets
    ignored, which is the failure the reconciliation exists to prevent.
    """
    if not tradingsymbol or tradingsymbol[0].isdigit():
        return False
    if tradingsymbol.endswith("INAV"):
        # Indicative NAV feeds for ETFs. Priced, published, and not tradable.
        return False
    return not DEBT_SUFFIX.search(tradingsymbol)


def bare_ticker(tradingsymbol: str) -> str:
    """Strip a series suffix, so `RELINFRA-BE` matches the bhavcopy's name."""
    for suffix in SERIES_SUFFIXES:
        if tradingsymbol.endswith(suffix):
            return tradingsymbol[: -len(suffix)]
    return tradingsymbol


@dataclass(frozen=True)
class BrokerLink:
    instrument_id: InstrumentId
    broker: str
    token: int
    tradingsymbol: str
    as_of: date
    """A token means nothing without a date, because tokens are reused."""


@dataclass
class MappingReport:
    linked: list[BrokerLink] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    skipped_non_equity: int = 0
    """Bonds and debentures in the broker list, excluded rather than counted
    as failures. Reported so the exclusion is visible, not silent."""
    """Broker symbols the master could not resolve on this date.

    Never silently dropped. An unmapped instrument is the single alert the
    playbook says matters most, because it is the shape of both a stale master
    and an about-to-be-wrong order.
    """

    @property
    def ok(self) -> bool:
        return not self.unmapped

    def summary(self) -> str:
        return (
            f"{len(self.linked)} mapped, {len(self.unmapped)} unmapped, "
            f"{self.skipped_non_equity} non-equity skipped"
        )


def build_mapping(
    registry: Registry,
    broker_instruments: dict[str, int],
    *,
    as_of: date,
    broker: str = "kite",
) -> MappingReport:
    """Resolve each broker ticker through the master as of `as_of`."""
    report = MappingReport()
    for tradingsymbol, token in sorted(broker_instruments.items()):
        if not is_equity_symbol(tradingsymbol):
            report.skipped_non_equity += 1
            continue
        instrument = registry.resolve(bare_ticker(tradingsymbol), as_of)
        if instrument is None:
            report.unmapped.append(tradingsymbol)
            continue
        report.linked.append(
            BrokerLink(
                instrument_id=instrument.instrument_id,
                broker=broker,
                token=token,
                tradingsymbol=tradingsymbol,
                as_of=as_of,
            )
        )
    return report


def detect_token_reuse(links: list[BrokerLink]) -> dict[int, list[InstrumentId]]:
    """Tokens pointing at more than one instrument — the reuse hazard, measured.

    An empty result is not proof of safety; it means no reuse is visible in
    *this* snapshot. Reuse shows up across time, which is why links carry a
    date.
    """
    by_token: dict[int, set[InstrumentId]] = {}
    for link in links:
        by_token.setdefault(link.token, set()).add(link.instrument_id)
    return {t: sorted(ids) for t, ids in by_token.items() if len(ids) > 1}
