"""The live NSE option chain, landed like any other source.

**What this adds that the bhavcopy cannot.** The F&O bhavcopy is the complete
end-of-day record and is already landed back to 2024, so nothing here is about
getting daily prices. It is about the two things the bhavcopy has no column
for: a **bid and an ask**, and NSE's own **implied volatility**. A settlement
price tells you where a contract was marked; a spread tells you what it would
have cost to get out of it, and that is the number a cost model needs.

**It can only ever record forward.** `/option-chain-v3` is a snapshot of right
now. There is no history behind it, so the first useful day is the first day
this runs, and no amount of effort recovers last month. That is the whole
reason to start it rather than plan it.

**This is NSE's website API, not a product.** Undocumented, unsupported, and
free to change shape or start refusing without notice. Treated accordingly:
every call is bounded, failures are reported rather than retried forever, and
nothing in the trading path depends on it.

The endpoints are called directly rather than through `jugaad-data`, which
wraps the same two URLs. That library carries no LICENSE file and GitHub
reports none, which makes it all-rights-reserved by default; the cookie
handling it provides is the forty lines below, so the dependency bought
nothing and cost a licence question.
"""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.paths import data_path

LANDING = data_path("landing/option_chain")

BASE = "https://www.nseindia.com"
CHAIN_URL = f"{BASE}/api/option-chain-v3"
CONTRACT_URL = f"{BASE}/api/option-chain-contract-info"
WARMUP_URL = f"{BASE}/option-chain"

CONNECT_TIMEOUT = 10.0
"""Short on purpose. A handshake that has not completed in ten seconds is not
going to, and this project has already lost nine hours to sockets left in
SYN_SENT with nothing bounding them (S-034)."""

READ_TIMEOUT = 30.0
ATTEMPTS = 3
BACKOFF = 2.0

INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE}/option-chain",
    "X-Requested-With": "XMLHttpRequest",
}


class ChainUnavailable(RuntimeError):
    """NSE did not serve a chain. Expected outside market hours and on blocks."""


@dataclass
class Snapshot:
    """One chain, for one expiry, as it stood at one instant."""

    symbol: str
    expiry: str
    taken_at: datetime
    underlying: float | None
    expiries: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def strikes(self) -> int:
        return len(self.rows)


def _session() -> Any:
    """A requests session carrying NSE's cookies.

    NSE serves its JSON only to a client that has first been issued cookies by
    the HTML page. Fetching the page is not politeness, it is the handshake.
    """
    import requests

    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(WARMUP_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    return session


def _get(client: Any, url: str, params: dict[str, str], what: str) -> dict[str, Any]:
    """One bounded GET with backoff, or `ChainUnavailable`."""
    import requests

    for attempt in range(ATTEMPTS):
        try:
            response = client.get(url, params=params, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            return payload
        except (requests.RequestException, ValueError) as exc:
            if attempt == ATTEMPTS - 1:
                msg = f"{what}: {type(exc).__name__}: {exc}"[:200]
                raise ChainUnavailable(msg) from exc
            time.sleep(BACKOFF * (2**attempt))
    raise ChainUnavailable(what)  # unreachable; satisfies the type checker


def expiries(symbol: str, *, session: Any) -> list[str]:
    """Listed expiries for one underlying, nearest first.

    A separate call because `/option-chain-v3` **requires** an expiry and
    returns an empty row set without one — not an error, an empty success,
    which is the shape that reads as "the market has no options today". The
    first version of this module omitted the parameter and reported four
    symbols as unavailable while NSE was serving all four perfectly well.
    """
    payload = _get(session, CONTRACT_URL, {"symbol": symbol}, f"{symbol} contract-info")
    dates = payload.get("expiryDates") or []
    return [str(d) for d in dates]


def fetch(symbol: str, expiry: str, *, session: Any) -> Snapshot:
    """One chain, for one underlying and one expiry.

    Raises rather than returning an empty snapshot when NSE refuses. An empty
    chain and a refused chain are different facts, and a caller that cannot
    tell them apart will land the second as though it were the first.
    """
    payload = _get(
        session,
        CHAIN_URL,
        {"type": "Indices", "symbol": symbol, "expiry": expiry},
        f"{symbol} {expiry}",
    )
    records = payload.get("records") or {}
    rows = records.get("data") or []
    if not rows:
        msg = f"{symbol} {expiry}: NSE returned no rows"
        raise ChainUnavailable(msg)

    return Snapshot(
        symbol=symbol,
        expiry=expiry,
        taken_at=datetime.now(UTC),
        underlying=records.get("underlyingValue"),
        expiries=list(records.get("expiryDates") or []),
        rows=rows,
    )


def _records(snapshot: Snapshot) -> list[dict[str, Any]]:
    """Flatten to one row per contract, bitemporally stamped.

    `event_time` is when the quote was true and `knowledge_time` is when we
    learned it, and for a live snapshot they are the same instant — which is
    the point of recording it rather than reconstructing it later. CLAUDE.md
    requires both on every stored record with no exceptions.
    """
    known = snapshot.taken_at.isoformat()
    out: list[dict[str, Any]] = []
    for row in snapshot.rows:
        strike = row.get("strikePrice")
        for right in ("CE", "PE"):
            leg = row.get(right)
            if not isinstance(leg, dict):
                continue
            out.append(
                {
                    "event_time": known,
                    "knowledge_time": known,
                    "underlying": snapshot.symbol,
                    "underlying_price": snapshot.underlying,
                    "expiry": leg.get("expiryDate"),
                    "strike": strike,
                    "right": right,
                    "last_price": leg.get("lastPrice"),
                    # The columns the bhavcopy does not have. This is the
                    # reason the recorder exists.
                    "bid": leg.get("buyPrice1"),
                    "bid_qty": leg.get("buyQuantity1"),
                    "ask": leg.get("sellPrice1"),
                    "ask_qty": leg.get("sellQuantity1"),
                    "implied_volatility": leg.get("impliedVolatility"),
                    "open_interest": leg.get("openInterest"),
                    "change_in_open_interest": leg.get("changeinOpenInterest"),
                    "volume": leg.get("totalTradedVolume"),
                    "total_buy_quantity": leg.get("totalBuyQuantity"),
                    "total_sell_quantity": leg.get("totalSellQuantity"),
                }
            )
    return out


def land(snapshot: Snapshot, *, directory: Path = LANDING) -> Path:
    """Write one snapshot. Returns the path written.

    One file per snapshot, named by the instant it was taken, because a
    snapshot is immutable once recorded. Appending to a daily file would make
    a re-run able to corrupt what an earlier one wrote, and CLAUDE.md puts
    landed data beyond editing.
    """
    stamp = snapshot.taken_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    day = snapshot.taken_at.strftime("%Y-%m-%d")
    safe = snapshot.expiry.replace(" ", "")
    target = directory / snapshot.symbol / day / f"{stamp}_{safe}.jsonl.gz"
    target.parent.mkdir(parents=True, exist_ok=True)

    body = "\n".join(json.dumps(record, separators=(",", ":")) for record in _records(snapshot))
    tmp = target.with_suffix(".partial")
    tmp.write_bytes(gzip.compress(body.encode("utf-8")))
    tmp.replace(target)
    return target


def snapshot_all(
    symbols: tuple[str, ...] = INDEX_SYMBOLS,
    *,
    directory: Path = LANDING,
    pace: float = 1.5,
    per_symbol: int = 4,
) -> tuple[list[Path], list[str]]:
    """A snapshot of each symbol's nearest expiries. Returns (written, problems).

    `per_symbol` is capped because the whole listed board is dozens of expiries
    and the far ones barely trade — four covers the weeklies plus the monthly,
    which is where the open interest is.

    Paced between every call. NSE blocks a client that asks too fast, and a
    recorder that gets itself blocked records nothing, so being slow is the
    cheapest way to keep working.
    """
    session = _session()
    written: list[Path] = []
    problems: list[str] = []
    try:
        for symbol in symbols:
            try:
                listed = expiries(symbol, session=session)
            except ChainUnavailable as exc:
                problems.append(str(exc))
                continue
            if not listed:
                problems.append(f"{symbol}: no expiries listed")
                continue
            for expiry in listed[:per_symbol]:
                time.sleep(pace)
                try:
                    written.append(
                        land(fetch(symbol, expiry, session=session), directory=directory)
                    )
                except (ChainUnavailable, OSError) as exc:
                    problems.append(str(exc)[:200])
    finally:
        session.close()
    return written, problems


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="nse-chain", description=__doc__)
    parser.add_argument("--symbols", nargs="*", default=list(INDEX_SYMBOLS))
    parser.add_argument("--landing", type=Path, default=LANDING)
    args = parser.parse_args(argv)

    written, problems = snapshot_all(tuple(args.symbols), directory=args.landing)
    for path in written:
        size = path.stat().st_size
        print(f"  landed {path}  ({size:,} bytes)")
    for problem in problems:
        print(f"  ! {problem}")
    if not written:
        print("nothing landed. NSE serves this only during and around market hours.")
        return 1
    print(f"{len(written)} snapshot(s), {len(problems)} problem(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
