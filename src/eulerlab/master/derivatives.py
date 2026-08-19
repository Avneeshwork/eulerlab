"""Identity for F&O contracts, which have no ISIN.

The cash bhavcopy carries an ISIN on every row. The F&O bhavcopy does not — in
either era — so derivatives cannot use the issuer-prefix key from
`identity.py`. Verified against real files: the UDiFF F&O schema has an `ISIN`
column that is empty for derivative rows, and the legacy F&O schema has no ISIN
column at all.

What uniquely identifies a contract is the natural composite: underlying,
expiry, and for options the strike and right. `FinInstrmId` exists in UDiFF but
is absent pre-2024 and, per Kite's own documentation, exchange tokens are
reused after expiry — so neither can key an eleven-year history.

The underlying is stored as the *symbol as written on the contract*, not
resolved to an equity instrument id. Resolving it is a separate step that needs
the trade date, because a rename changes what the symbol means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Right(StrEnum):
    CALL = "CE"
    PUT = "PE"


class ContractType(StrEnum):
    FUTURE = "FUT"
    OPTION = "OPT"


@dataclass(frozen=True, order=True)
class ContractId:
    """The natural key for a derivative contract.

    Frozen and ordered so it can be a dict key and sorted deterministically —
    determinism being a project-wide rule.
    """

    underlying: str
    expiry: date
    contract_type: ContractType
    strike: Decimal | None = None
    right: Right | None = None

    def __post_init__(self) -> None:
        if self.contract_type is ContractType.OPTION:
            if self.strike is None or self.right is None:
                msg = f"an option needs a strike and a right: {self.underlying} {self.expiry}"
                raise ValueError(msg)
        elif self.strike is not None or self.right is not None:
            msg = "a future has no strike or right"
            raise ValueError(msg)

    def __str__(self) -> str:
        if self.contract_type is ContractType.FUTURE:
            return f"{self.underlying}|{self.expiry.isoformat()}|FUT"
        return f"{self.underlying}|{self.expiry.isoformat()}|{self.strike}|{self.right}"


def parse_legacy_row(row: dict[str, str]) -> ContractId | None:
    """Build a ContractId from a pre-2024 F&O bhavcopy row.

    Legacy columns: INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP.
    `OPTION_TYP` is 'XX' for futures, which is the marker used to tell them
    apart — a strike of 0 alone is not reliable.
    """
    instrument = (row.get("INSTRUMENT") or "").strip().upper()
    symbol = (row.get("SYMBOL") or "").strip()
    expiry_raw = (row.get("EXPIRY_DT") or "").strip()
    if not symbol or not expiry_raw or not instrument:
        return None

    expiry = _parse_legacy_date(expiry_raw)
    if expiry is None:
        return None

    option_type = (row.get("OPTION_TYP") or "").strip().upper()
    if option_type in ("CE", "PE"):
        strike_raw = (row.get("STRIKE_PR") or "").strip()
        try:
            strike = Decimal(strike_raw)
        except Exception:
            return None
        return ContractId(symbol, expiry, ContractType.OPTION, strike, Right(option_type))
    return ContractId(symbol, expiry, ContractType.FUTURE)


_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _parse_legacy_date(text: str) -> date | None:
    """Legacy expiries look like '29-Jan-2015'. Parsed without strptime, which
    is locale-sensitive and would silently fail on a non-English machine."""
    parts = text.split("-")
    if len(parts) != 3:
        return None
    day, month_name, year = parts
    month = _MONTHS.get(month_name[:3].upper())
    if month is None or not day.isdigit() or not year.isdigit():
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_udiff_row(row: dict[str, str]) -> ContractId | None:
    """Build a ContractId from a 2024+ UDiFF F&O bhavcopy row.

    UDiFF columns: TckrSymb, XpryDt (ISO), StrkPric, OptnTp, FinInstrmTp.
    `OptnTp` is blank for futures.
    """
    symbol = (row.get("TckrSymb") or "").strip()
    expiry_raw = (row.get("XpryDt") or "").strip()
    if not symbol or not expiry_raw:
        return None
    try:
        expiry = date.fromisoformat(expiry_raw)
    except ValueError:
        return None

    option_type = (row.get("OptnTp") or "").strip().upper()
    if option_type in ("CE", "PE"):
        try:
            strike = Decimal((row.get("StrkPric") or "").strip())
        except Exception:
            return None
        return ContractId(symbol, expiry, ContractType.OPTION, strike, Right(option_type))
    return ContractId(symbol, expiry, ContractType.FUTURE)
