"""Index levels — India from the broker, the world from FMP when it is keyed.

### Why the split

The snapshot said "There is no index here" for as long as it has existed, and
that was true: the panel holds constituents, not levels, so breadth had nothing
to diverge from and a mover could not be read against its market.

Zerodha quotes NSE and BSE indices directly, so India is solved with the token
this platform already mints. The rest of the world is not: measured 2026-08-24,
**Yahoo answers 429, Stooq now serves a JavaScript proof-of-work challenge,
FRED times out on every series, and NSE's own quote endpoint 403s**. Four free
sources, four different walls.

So world indices come from FMP, which needs a key. Until one is present the band
reports that plainly rather than rendering an empty row — an absent index looks
identical to a flat one, and only one of those is true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

INDIA = (
    ("NSE:NIFTY 50", "NIFTY 50"),
    ("NSE:NIFTY BANK", "BANK NIFTY"),
    ("NSE:NIFTY MIDCAP 100", "MIDCAP 100"),
    ("NSE:NIFTY IT", "NIFTY IT"),
    ("BSE:SENSEX", "SENSEX"),
    ("NSE:INDIA VIX", "INDIA VIX"),
)
"""Instrument key → display name. Broad market, banks, midcaps, one sector and
volatility: enough to say what kind of day it was, not a full index list."""

WORLD = (
    ("^GSPC", "S&P 500", "US"),
    ("^IXIC", "NASDAQ", "US"),
    ("^DJI", "DOW", "US"),
    ("^FTSE", "FTSE 100", "UK"),
    ("^GDAXI", "DAX", "DE"),
    ("^N225", "NIKKEI 225", "JP"),
    ("^HSI", "HANG SENG", "HK"),
)
"""The indices a trader in India actually watches for context — the overnight
US close and the Asian session that opens before NSE does."""


CRYPTO = (
    ("BTCUSD", "BITCOIN", "CRYPTO"),
    ("ETHUSD", "ETHEREUM", "CRYPTO"),
    ("SOLUSD", "SOLANA", "CRYPTO"),
    ("XRPUSD", "XRP", "CRYPTO"),
    ("BNBUSD", "BNB", "CRYPTO"),
    ("DOGEUSD", "DOGECOIN", "CRYPTO"),
)
"""Majors by market value. Deliberately not the twenty pairs in the landed
archive: this is a ribbon, and a ribbon of twenty is a table."""

FX = (
    ("EURUSD", "EUR/USD", "FX"),
    ("USDINR", "USD/INR", "FX"),
    ("USDJPY", "USD/JPY", "FX"),
    ("GBPUSD", "GBP/USD", "FX"),
    ("AUDUSD", "AUD/USD", "FX"),
    ("USDCNY", "USD/CNY", "FX"),
)
"""USD/INR sits second because it is the pair that actually reprices an Indian
book overnight, whatever the global convention about majors."""


@dataclass(frozen=True)
class Level:
    """One index, and how it moved."""

    symbol: str
    name: str
    last: float
    previous_close: float
    region: str
    source: str
    at: str

    @property
    def change_pct(self) -> float:
        if not self.previous_close:
            return 0.0
        return (self.last - self.previous_close) / self.previous_close * 100.0


@dataclass
class Levels:
    """A sweep's result, and what it could not reach."""

    india: list[Level] = field(default_factory=list)
    world: list[Level] = field(default_factory=list)
    crypto: list[Level] = field(default_factory=list)
    fx: list[Level] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def any(self) -> bool:
        return bool(self.india or self.world or self.crypto or self.fx)


def from_zerodha() -> tuple[list[Level], str]:
    """India's indices. Returns (levels, error)."""
    try:
        from kiteconnect import KiteConnect

        from eulerlab.broker import kite_session
        from eulerlab.quotes import _env
    except ImportError as exc:
        return [], f"kiteconnect unavailable: {exc}"

    session = kite_session.load()
    if session is None:
        return [], "no Kite session — run `make kite-login` to mint a token"
    api_key = _env("ZERODHA_API_KEY")
    if not api_key:
        return [], "ZERODHA_API_KEY is not set"

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(session.access_token)
    stamp = datetime.now(UTC).isoformat()
    try:
        payload = kite.quote([key for key, _ in INDIA])
    except Exception as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:120]}"

    names = dict(INDIA)
    out: list[Level] = []
    for key, row in payload.items():
        last = row.get("last_price")
        close = (row.get("ohlc") or {}).get("close")
        if not isinstance(last, (int, float)) or not last:
            continue
        out.append(
            Level(
                symbol=key.split(":", 1)[-1],
                name=names.get(key, key),
                last=float(last),
                previous_close=float(close) if isinstance(close, (int, float)) else 0.0,
                region="IN",
                source="zerodha",
                at=stamp,
            )
        )
    # Kite returns a dict, so the order is not the one asked for. Restored, since
    # the ribbon reads left to right from broad market to volatility.
    order = {name: i for i, (_, name) in enumerate(INDIA)}
    out.sort(key=lambda level: order.get(level.name, 99))
    return out, ""


def from_fmp() -> tuple[list[Level], str]:
    """World indices from FMP. Returns (levels, error).

    Needs `FMP_API_KEY`. Whether index quotes sit on the free tier is
    **unverified** — FMP's plan matrix puts news on a paid tier and says
    nothing definitive about indices, so `make fmp-probe` answers it in one
    command rather than this module assuming either way.
    """
    from eulerlab.ingest import fmp

    if not fmp.key_present():
        return [], "no FMP_API_KEY — world indices need a key (see `make fmp-probe`)"

    stamp = datetime.now(UTC).isoformat()
    out: list[Level] = []
    refused = ""

    # One call per index, not `batch-index-quotes`. Probed 2026-08-24: the
    # batch endpoint answers **402 Payment Required** on the free plan while
    # the singular `quote` does not. Seven calls against a 250-a-day budget is
    # a price worth paying for the only world data this platform can reach.
    for symbol, label, region in WORLD:
        try:
            payload = fmp._get("quote", {"symbol": symbol})
        except Exception as exc:
            # Carry on rather than stop. Coverage is per index on the free
            # plan — S&P, Nasdaq, Dow and FTSE answer while DAX does not — and
            # breaking on the first refusal meant Nikkei and Hang Seng were
            # never even asked. One paywalled index is not a reason to drop
            # the ones that work.
            refused = f"{type(exc).__name__}: {str(exc)[:100]}"
            continue

        rows = payload if isinstance(payload, list) else [payload]
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        last = row.get("price")
        close = row.get("previousClose")
        if not isinstance(last, (int, float)) or not last:
            continue
        out.append(
            Level(
                symbol=symbol,
                name=label,
                last=float(last),
                previous_close=float(close) if isinstance(close, (int, float)) else 0.0,
                region=region,
                source="fmp",
                at=stamp,
            )
        )

    if not out:
        return [], refused or "FMP answered but carried none of the indices asked for"
    return out, refused


def quote_group(
    group: tuple[tuple[str, str, str], ...],
    *,
    source: str = "fmp",
) -> tuple[list[Level], str]:
    """Quote a named set of symbols. Returns (levels, error).

    One call per symbol, as with the world indices: `batch-*` endpoints answer
    402 on the free plan. A refusal on one symbol does not stop the rest —
    coverage is per instrument, and dropping five because a sixth is paywalled
    was already a bug once.
    """
    from eulerlab.ingest import fmp

    if not fmp.key_present():
        return [], "no FMP_API_KEY"

    stamp = datetime.now(UTC).isoformat()
    out: list[Level] = []
    refused = ""
    for symbol, label, region in group:
        try:
            payload = fmp._get("quote", {"symbol": symbol})
        except Exception as exc:
            refused = f"{type(exc).__name__}: {str(exc)[:90]}"
            continue
        rows = payload if isinstance(payload, list) else [payload]
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        last = row.get("price")
        close = row.get("previousClose")
        if not isinstance(last, (int, float)) or not last:
            continue
        out.append(
            Level(
                symbol=symbol,
                name=label,
                last=float(last),
                previous_close=float(close) if isinstance(close, (int, float)) else 0.0,
                region=region,
                source=source,
                at=stamp,
            )
        )
    return out, refused


def levels() -> Levels:
    """India and world together, each reporting its own failure."""
    result = Levels()
    india, india_error = from_zerodha()
    result.india = india
    if india_error:
        result.errors["india"] = india_error

    world, world_error = from_fmp()
    result.world = world
    if world_error:
        result.errors["world"] = world_error

    crypto, crypto_error = quote_group(CRYPTO)
    result.crypto = crypto
    if crypto_error:
        result.errors["crypto"] = crypto_error

    fx, fx_error = quote_group(FX)
    result.fx = fx
    if fx_error:
        result.errors["fx"] = fx_error
    return result


@dataclass(frozen=True)
class Mover:
    """One stock moving hard, anywhere."""

    symbol: str
    name: str
    price: float
    change_pct: float
    exchange: str
    kind: str
    """`gainer`, `loser` or `active`."""


MOVER_FEEDS = (
    ("gainer", "biggest-gainers"),
    ("loser", "biggest-losers"),
    ("active", "most-actives"),
)


PRICE_FLOOR = 5.0
"""Minimum price for a world mover to be shown.

Measured on the raw feed 2026-08-24: the **median price of a "biggest mover"
was $4.75**, and the top gainer was a $0.52 shell up 57%. A band that exists to
give overnight context is not helped by a micro-cap doubling — it is drowned by
it. A $5 floor keeps 73 of 150 and lifts the median to $18.91.

What the floor does **not** fix, and is worth knowing: leveraged ETFs survive
it, so a single move in one underlying can appear three times under three
tickers (HODU, HOOX and HOOG are all 2x HOOD). Filtering those means pattern
matching on fund names, which is a rule invented rather than measured, so they
are left in and this note stands instead.
"""


def world_movers(*, per_feed: int = 8, floor: float = PRICE_FLOOR) -> tuple[list[Mover], str]:
    """The day's biggest movers outside India. Returns (movers, error).

    Free on FMP — probed 2026-08-24, fifty rows per feed — which makes this the
    one genuinely global thing this platform can show. The snapshot has only
    ever known NSE, so a 12% move on a US name was invisible here no matter how
    much it mattered to the open.

    Trimmed to eight per feed. Fifty is a screener, not a snapshot, and the
    band exists to say what is happening rather than to be scrolled.
    """
    from eulerlab.ingest import fmp

    if not fmp.key_present():
        return [], "no FMP_API_KEY — world movers need a key (see `make fmp-probe`)"

    out: list[Mover] = []
    refused = ""
    for kind, endpoint in MOVER_FEEDS:
        try:
            payload = fmp._get(endpoint, {})
        except Exception as exc:
            refused = f"{type(exc).__name__}: {str(exc)[:100]}"
            continue

        rows = payload if isinstance(payload, list) else []
        taken = 0
        for row in rows:
            if not isinstance(row, dict) or taken >= per_feed:
                continue
            price = row.get("price")
            change = row.get("changesPercentage", row.get("changePercentage"))
            symbol = str(row.get("symbol", "")).strip()
            if not symbol or not isinstance(price, (int, float)):
                continue
            if float(price) < floor:
                continue
            out.append(
                Mover(
                    symbol=symbol,
                    name=str(row.get("name", "")).strip(),
                    price=float(price),
                    change_pct=float(change) if isinstance(change, (int, float)) else 0.0,
                    exchange=str(row.get("exchange", "")).strip(),
                    kind=kind,
                )
            )
            taken += 1
    return out, refused


@dataclass(frozen=True)
class SectorMove:
    """How one sector moved, on one exchange."""

    sector: str
    change_pct: float
    exchange: str


def world_sectors(*, on: str = "") -> tuple[list[SectorMove], str]:
    """US sector performance for a session. Returns (sectors, error).

    Free on FMP, and the closest thing the US view has to India's map: eleven
    named sectors with an average change is a shape-of-the-session answer, even
    without the constituent grid underneath it.

    Defaults to the most recent weekday rather than today, because the endpoint
    is dated and a request for a day the US market has not closed on returns
    nothing — which would render as "no sectors" when the truth is "not yet".
    """
    from datetime import timedelta

    from eulerlab.ingest import fmp

    if not fmp.key_present():
        return [], "no FMP_API_KEY — US sectors need a key"

    when = on
    if not when:
        # UTC explicitly: a naive `today()` reads the machine's zone, and this
        # asks about a US session from a machine in IST.
        day = (datetime.now(UTC) - timedelta(days=1)).date()
        while day.weekday() >= 5:  # Saturday or Sunday
            day -= timedelta(days=1)
        when = day.isoformat()

    try:
        payload = fmp._get("sector-performance-snapshot", {"date": when})
    except Exception as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:100]}"

    rows = payload if isinstance(payload, list) else []
    out: list[SectorMove] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("sector", "")).strip()
        change = row.get("averageChange")
        if not name or not isinstance(change, (int, float)):
            continue
        out.append(
            SectorMove(
                sector=name,
                change_pct=float(change),
                exchange=str(row.get("exchange", "")).strip(),
            )
        )
    out.sort(key=lambda s: -s.change_pct)
    return out, ""


LANDING = Path("data/landing/marketdata")
"""Where a sweep is written. Landed rather than fetched per render.

The arithmetic forces it. A full sweep is **29 FMP calls** — six India indices
via the broker are free, but seven world indices, six crypto, six FX, three
mover feeds and one sector snapshot are not — against a free budget of **250 a
day**. Even a three-hour cache is eight sweeps, 232 calls, and leaves nothing
for anything else; a ten-minute cache would spend the day's allowance before
lunch.

So `make world` sweeps once and writes a file, and the snapshot reads it. The
levels are minutes-to-hours old rather than seconds, which for a screen whose
other numbers are end-of-day is the right trade — and the file records when it
was taken so the page can say so instead of implying live.
"""


def snapshot_path(day: str = "", *, root: Path = LANDING) -> Path:
    stamp = day or datetime.now(UTC).date().isoformat()
    return root / f"{stamp}.json"


def land(*, root: Path = LANDING) -> dict[str, object]:
    """Sweep every group once and write it. Returns the payload."""
    import json

    found = levels()
    movers, mover_error = world_movers()
    sectors, sector_error = world_sectors()

    errors = dict(found.errors)
    if mover_error:
        errors["movers"] = mover_error
    if sector_error:
        errors["sectors"] = sector_error

    def level_row(level: Level) -> dict[str, object]:
        return {
            "symbol": level.symbol,
            "name": level.name,
            "last": round(level.last, 4),
            "change_pct": round(level.change_pct, 2),
            "region": level.region,
            "source": level.source,
        }

    payload: dict[str, object] = {
        "taken_at": datetime.now(UTC).isoformat(),
        "india": [level_row(x) for x in found.india],
        "world": [level_row(x) for x in found.world],
        "crypto": [level_row(x) for x in found.crypto],
        "fx": [level_row(x) for x in found.fx],
        "movers": [
            {
                "symbol": m.symbol,
                "name": m.name,
                "price": round(m.price, 2),
                "change_pct": round(m.change_pct, 2),
                "exchange": m.exchange,
                "kind": m.kind,
            }
            for m in movers
        ],
        "sectors": [
            {"sector": x.sector, "change_pct": round(x.change_pct, 2), "exchange": x.exchange}
            for x in sectors
        ],
        "errors": errors,
    }

    root.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(root=root)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(path)
    return payload


def load(*, root: Path = LANDING, allow_cloud: bool = True) -> dict[str, object] | None:
    """The newest landed sweep, or None when none has been taken.

    None rather than an empty payload: "not swept yet" and "swept, everything
    flat" look identical once the levels are gone, and only one of them means
    the operator should run `make world`.

    Reads the bucket as well as the disk. `prune-local` moves landed files to
    B2 and leaves the tree empty, so a local-only glob reported a swept file as
    never taken — the whole index ribbon went blank the first time a prune ran
    after a sweep. That is the third time this session a reader has been
    written against the disk alone; the landing zone is the union of disk and
    bucket, and anything that forgets it works until the next prune.
    """
    import json

    files = sorted(root.glob("????-??-??.json"))
    if files:
        try:
            loaded = json.loads(files[-1].read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    if not allow_cloud:
        return None

    from eulerlab.ingest import landing_reader

    remote = sorted(landing_reader.available("marketdata", "*.json"))
    if not remote:
        return None
    try:
        payload = landing_reader.read(remote[-1])
        loaded = json.loads(payload.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _main() -> None:
    payload = land()
    counts = {k: len(v) for k, v in payload.items() if isinstance(v, list)}
    print(f"world sweep -> {snapshot_path()}")
    for name, count in sorted(counts.items()):
        print(f"  {name:9s} {count:>3}")
    errors = payload.get("errors")
    if isinstance(errors, dict) and errors:
        for name, why in errors.items():
            print(f"  ! {name}: {str(why)[:80]}")


if __name__ == "__main__":
    _main()
