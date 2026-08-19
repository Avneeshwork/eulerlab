"""Instrument identity — which strings may be trusted as join keys, and when.

Everything here is derived from measurements against our own bhavcopy history
(2023-06-15 vs 2026-08-14), not from assumption. The measurements are recorded
in ``docs/RESEARCH/006-instrument-identity.md``.

**No single string is a permanent identifier.** That is the whole problem:

* **Ticker** is not stable. 131 renames were observed in a three-year window
  (ZOMATO to ETERNAL, GMRINFRA to GMRAIRPORT). Worse, a ticker can be *reused*:
  149 tickers pointed at a different ISIN in 2026 than in 2023.
* **ISIN** survives renames — ZOMATO and ETERNAL share ``INE758T01015`` — but it
  does *not* survive every corporate action. 139 of those 149 kept the same
  ISIN issuer prefix and only had the trailing digits reissued, which is a
  split, consolidation or face-value change on the same underlying company.
* **Exchange instrument id** (``FinInstrmId``) exists only in the UDiFF era and
  is absent from every pre-2024 file, so it cannot key a history that starts in
  2015. Kite's equivalent token is documented as reused after expiry.

So the internal id is derived from the **ISIN issuer prefix** — the first ten
characters, which identify the issuer and survive the reissue — with the full
ISIN and the ticker both recorded as *time-versioned attributes* rather than
keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# An ISIN is 12 characters: 2-letter country + 9-character NSIN + 1 check
# digit. Getting this wrong by one rejected a real ISIN outright, which is
# precisely the failure a regex written from memory produces.
ISIN_RE = re.compile(r"^IN[EF0-9][0-9A-Z]{8}[0-9]$")

ISSUER_PREFIX_LEN = 10
"""An Indian ISIN is IN + issuer code + security serial + check digit.

The first ten characters identify the *issuer*; the tail is reissued when a
corporate action changes the security (split, consolidation, face-value
change). Measured: 139 of 149 ISIN changes over three years preserved this
prefix, i.e. they were the same company, not a different one.
"""


class NotAnIsin(ValueError):
    """The string is not a well-formed Indian ISIN."""


@dataclass(frozen=True, order=True)
class InstrumentId:
    """The internal join key. Never a ticker, never an exchange token.

    Two securities share an ``InstrumentId`` when they are the same issuer's
    equity line, even across a rename or a face-value reissue. They differ when
    the issuer differs.
    """

    issuer: str

    def __str__(self) -> str:
        return self.issuer

    @classmethod
    def from_isin(cls, isin: str) -> InstrumentId:
        cleaned = (isin or "").strip().upper()
        if not ISIN_RE.match(cleaned):
            msg = f"not a well-formed Indian ISIN: {isin!r}"
            raise NotAnIsin(msg)
        return cls(issuer=cleaned[:ISSUER_PREFIX_LEN])


def is_equity_isin(isin: str) -> bool:
    """True for company equity (INE...), false for fund/ETF units (INF...).

    The distinction matters: the 10 genuinely-different-security cases found in
    the 2023-to-2026 comparison were all INF-prefixed fund units, where a new
    ISIN really does mean a new instrument rather than a reissue.
    """
    cleaned = (isin or "").strip().upper()
    return bool(ISIN_RE.match(cleaned)) and cleaned.startswith("INE")
