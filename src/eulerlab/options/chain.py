"""One day's option chain, read out of the F&O bhavcopy.

Sprint 2's intraday recorder has never run, so there are no 5-second chain
snapshots. What does exist is 2,868 days of end-of-day F&O bhavcopy, and that
*is* a chain: every strike, every expiry, both rights, with a close, a
settlement price and open interest. The no-arbitrage mathematics is identical
on a daily snapshot; only the resolution differs.

**Two facts about this data shape every check built on it.**

*Settlement prices are not always traded prices.* NSE computes a settlement
price for every listed contract, including strikes that saw no trade all day,
using its own model. A parity violation on an untraded strike therefore tells
you about NSE's model, not about the market. Every quote carries `traded` so a
check can separate the two, and any check that ignores it is measuring the
exchange rather than the data.

*There is no underlying price in the legacy era.* The pre-2024 F&O file has no
underlying column, and an index level is not in the cash bhavcopy either. But
the same-expiry **future** is in the same file, so parity is checked in its
futures form against that. This works in both eras, needs no external data,
and is the right form regardless: Indian index options are European and
cash-settled, which is why Black-76 rather than Black-Scholes applies.

Contract identity comes from `eulerlab.master.derivatives`, unchanged — the
composite key was built and validated in Sprint 3 against real files in both
eras, and a second parser here would be a second thing to get wrong.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from eulerlab.master.derivatives import (
    ContractType,
    Right,
    parse_legacy_row,
    parse_udiff_row,
)

CLOSE_FIELDS = ("ClsPric", "CLOSE")
SETTLE_FIELDS = ("SttlmPric", "SETTLE_PR")
VOLUME_FIELDS = ("TtlTradgVol", "CONTRACTS")
OI_FIELDS = ("OpnIntrst", "OPEN_INT")
UNDERLYING_FIELDS = ("UndrlygPric",)
OPEN_FIELDS = ("OpnPric", "OPEN")
HIGH_FIELDS = ("HghPric", "HIGH")
LOW_FIELDS = ("LwPric", "LOW")
LAST_FIELDS = ("LastPric",)
OI_CHANGE_FIELDS = ("ChngInOpnIntrst", "CHG_IN_OI")
TURNOVER_FIELDS = ("TtlTrfVal", "VAL_INLAKH")
TRADES_FIELDS = ("TtlNbOfTxsExctd",)
LOT_FIELDS = ("NewBrdLotQty",)


def _text(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if value := row.get(name):
            return value.strip()
    return ""


def _number(row: dict[str, str], names: tuple[str, ...]) -> float | None:
    raw = _text(row, names)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Quote:
    """One contract's end-of-day state."""

    underlying: str
    expiry: date
    contract_type: ContractType
    price: float
    """Settlement price where present, else close. Settlement is the exchange's
    official mark and is populated for every listed contract; close is blank
    for anything that did not trade."""

    strike: Decimal | None = None
    right: Right | None = None
    volume: float = 0.0
    open_interest: float = 0.0
    underlying_price: float | None = None

    # The rest of what the bhavcopy already carries.
    #
    # These columns have been in every file this project has ever landed and
    # were simply not read. The parser kept the settlement price, volume and
    # open interest and dropped the rest, so three months of intraday range,
    # open-interest *change*, turnover and trade count sat in B2 unreadable —
    # and the gap looked like missing data rather than an unfinished parser.
    # Checked against the live NSE chain before adding: this is a superset of
    # what jugaad-data's historical endpoint returns, so there was nothing to
    # go and fetch.
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    last_price: float | None = None
    open_interest_change: float = 0.0
    turnover: float = 0.0
    trades: float = 0.0
    lot_size: float | None = None

    @property
    def traded(self) -> bool:
        """Whether anyone actually transacted this contract today.

        The single most important field for interpreting a violation: an
        untraded contract's price is NSE's model output, so a "violation"
        involving it is a statement about that model.
        """
        return self.volume > 0

    @property
    def is_option(self) -> bool:
        return self.contract_type is ContractType.OPTION


@dataclass
class Chain:
    """Every quote for one underlying and expiry on one day."""

    underlying: str
    expiry: date
    day: date
    calls: dict[Decimal, Quote] = field(default_factory=dict)
    puts: dict[Decimal, Quote] = field(default_factory=dict)
    future: Quote | None = None

    @property
    def strikes(self) -> list[Decimal]:
        """Strikes with both a call and a put, sorted.

        Parity and butterfly checks need the pair, and sorting makes every
        result deterministic.
        """
        return sorted(set(self.calls) & set(self.puts))

    def paired(self, *, traded_only: bool = False) -> list[tuple[Decimal, Quote, Quote]]:
        out = []
        for strike in self.strikes:
            call, put = self.calls[strike], self.puts[strike]
            if traded_only and not (call.traded and put.traded):
                continue
            out.append((strike, call, put))
        return out


SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
"""The underlying's column: UDiFF, then the pre-2024 layout."""


def quotes_from_fo_bhavcopy(payload: bytes, underlying: str = "") -> Iterator[Quote]:
    """Every derivative quote in one F&O bhavcopy, either era.

    `underlying` keeps one name's rows and drops the rest before they are
    parsed. A day's file is about 35,000 contracts across 200 names, and a
    screen showing NIFTY was parsing all of them: 2.5 s a day, 75 s for the
    30-day history (measured 2026-10-12). The filter reads one cell of each
    row; the rows it keeps are parsed exactly as before.
    """
    wanted = underlying.strip().upper()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return
        with archive.open(names[0]) as handle:
            # Bytes first: a line that does not contain the name at all is
            # dropped before it is decoded or split into cells. The exact test
            # on the symbol cell still follows, so NIFTY does not let
            # BANKNIFTY or NIFTYNXT50 through.
            needle = wanted.encode()
            lines = (
                line.decode("utf-8", errors="replace")
                for number, line in enumerate(handle)
                if number == 0 or not wanted or needle in line.upper()
            )
            reader = csv.reader(lines)
            header = [(name or "").strip() for name in next(reader, [])]
            symbol_at = next((header.index(f) for f in SYMBOL_FIELDS if f in header), -1)
            for cells in reader:
                if wanted and (
                    symbol_at < 0
                    or symbol_at >= len(cells)
                    or cells[symbol_at].strip().upper() != wanted
                ):
                    continue
                row = {
                    name: (value or "").strip() for name, value in zip(header, cells, strict=False)
                }
                contract = parse_udiff_row(row) or parse_legacy_row(row)
                if contract is None:
                    continue
                price = _number(row, SETTLE_FIELDS)
                if price is None:
                    price = _number(row, CLOSE_FIELDS)
                if price is None:
                    continue
                yield Quote(
                    underlying=contract.underlying,
                    expiry=contract.expiry,
                    contract_type=contract.contract_type,
                    price=price,
                    strike=contract.strike,
                    right=contract.right,
                    volume=_number(row, VOLUME_FIELDS) or 0.0,
                    open_interest=_number(row, OI_FIELDS) or 0.0,
                    underlying_price=_number(row, UNDERLYING_FIELDS),
                    open_price=_number(row, OPEN_FIELDS),
                    high=_number(row, HIGH_FIELDS),
                    low=_number(row, LOW_FIELDS),
                    last_price=_number(row, LAST_FIELDS),
                    open_interest_change=_number(row, OI_CHANGE_FIELDS) or 0.0,
                    turnover=_number(row, TURNOVER_FIELDS) or 0.0,
                    trades=_number(row, TRADES_FIELDS) or 0.0,
                    lot_size=_number(row, LOT_FIELDS),
                )


def build_chains(quotes: Iterator[Quote] | list[Quote], day: date) -> list[Chain]:
    """Group quotes into one chain per (underlying, expiry).

    Returned in sorted order so a report reads the same way twice.
    """
    grouped: dict[tuple[str, date], Chain] = {}
    for quote in quotes:
        key = (quote.underlying, quote.expiry)
        chain = grouped.get(key)
        if chain is None:
            chain = Chain(underlying=quote.underlying, expiry=quote.expiry, day=day)
            grouped[key] = chain

        if quote.contract_type is ContractType.FUTURE:
            chain.future = quote
        elif quote.strike is not None:
            target = chain.calls if quote.right is Right.CALL else chain.puts
            target[quote.strike] = quote

    return [grouped[key] for key in sorted(grouped)]
