"""A derived US price panel, built from the landed Alpaca bars.

### Why a derived file rather than reading the landing zone

The bars live as one gzipped file per symbol per month — 36,446 of them — and
`prune-local` has moved every one to B2. Reading them per request would be
thousands of network round trips to render one screen, which is the mistake
this platform has already made twice: once when `capabilities()` listed the
bucket to build a description string, and once when the snapshot fetched news
at render time and hung for 576 seconds.

So the landing zone is read **once**, by an ingest, into a compact local file —
exactly the shape `price_panel.jsonl` takes for India. The read path opens one
file.

### Scoped by window, deliberately

`build(years=2)` is the default rather than the full decade. The snapshot needs
breadth, a map and movers, all of which come from the last two sessions; two
years is enough for a 252-day return and leaves the file small enough to load
in a second. The decade is still in B2 for anything that wants it.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PANEL_PATH = Path("data/derived/us_panel.jsonl")


@dataclass(frozen=True)
class UsRow:
    """One symbol on one day."""

    day: date
    symbol: str
    close: float
    volume: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0

    @property
    def turnover(self) -> float:
        """Close x volume. Alpaca publishes no notional, so this is derived the
        same way the crypto panel derives it — one definition across asset
        classes rather than two that nearly agree."""
        return self.close * self.volume


def _months_wanted(years: float) -> set[str]:
    """Which monthly files can hold anything in the window."""
    now = datetime.now(UTC).date()
    first = now - timedelta(days=int(365 * years) + 5)
    out: set[str] = set()
    cursor = date(first.year, first.month, 1)
    while cursor <= now:
        out.add(cursor.strftime("%Y-%m"))
        cursor = date(cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1)
    return out


def build(*, years: float = 2.0, path: Path = PANEL_PATH) -> tuple[int, int]:
    """Read the landed bars into one file. Returns (rows, symbols).

    Slow by design and run once: every monthly file in the window is fetched
    from B2 if it is not local, and `landing_reader` caches it on the way
    through, so a rebuild is fast even though the first build is not.
    """
    from eulerlab.ingest import landing_reader

    wanted = _months_wanted(years)
    listed = landing_reader.available("us", "bars/*/*.jsonl.gz")
    relevant = [r for r in listed if r.rsplit("/", 1)[-1][:7] in wanted]

    rows: list[UsRow] = []
    symbols: set[str] = set()
    missed: list[str] = []
    for relative in sorted(relevant):
        try:
            payload = gzip.decompress(landing_reader.read(relative))
        except Exception:
            # Broad on purpose. The narrow version caught OSError, ValueError
            # and FileNotFoundError, and botocore raises
            # `EndpointConnectionError`, which is none of them — so a single
            # transient network blip killed an hour-long build at symbol 280 of
            # 502 and lost every file it had already fetched.
            #
            # A month that cannot be read is absent from the panel, which shows
            # up in the row count. One unreadable file must not cost the other
            # twelve thousand.
            missed.append(relative)
            continue
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                when = date.fromisoformat(str(row["event_time"])[:10])
                close = float(row["close"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if close <= 0:
                continue
            symbol = str(row.get("symbol", ""))
            symbols.add(symbol)
            rows.append(
                UsRow(
                    day=when,
                    symbol=symbol,
                    close=close,
                    volume=float(row.get("volume", 0.0)),
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                )
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda r: (r.day, r.symbol)):
            handle.write(
                json.dumps(
                    {
                        "d": row.day.isoformat(),
                        "s": row.symbol,
                        "c": round(row.close, 4),
                        "v": row.volume,
                        "o": round(row.open, 4),
                        "h": round(row.high, 4),
                        "l": round(row.low, 4),
                    }
                )
                + "\n"
            )
    tmp.replace(path)
    if missed:
        # Reported, not swallowed. A build that skipped four hundred files is
        # a different thing from one that skipped none, and the row count
        # alone does not distinguish them.
        print(f"  {len(missed)} file(s) unreadable, e.g. {missed[:2]}")
    return len(rows), len(symbols)


def read(path: Path = PANEL_PATH) -> list[UsRow]:
    """Every row in the derived panel. One file, one pass."""
    if not path.exists():
        return []
    out: list[UsRow] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                out.append(
                    UsRow(
                        day=date.fromisoformat(row["d"]),
                        symbol=str(row["s"]),
                        close=float(row["c"]),
                        volume=float(row.get("v", 0.0)),
                        open=float(row.get("o", 0.0)),
                        high=float(row.get("h", 0.0)),
                        low=float(row.get("l", 0.0)),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    return out


def sectors(*, root: Path = Path("data/landing/us")) -> dict[str, str]:
    """Symbol → GICS sector, from the landed constituent snapshot.

    Used for grouping the map only. The snapshot is today's membership, so a
    symbol that left the index has no sector here and groups under the
    unclassified heading rather than being dropped — a missing label is a gap
    in the data, not a reason to hide the company.
    """
    from eulerlab.ingest import landing_reader

    files = sorted((root / "sp500").glob("????-??-??.jsonl.gz"))
    payloads: list[bytes] = []
    if files:
        payloads.append(files[-1].read_bytes())
    else:
        remote = sorted(landing_reader.available("us", "sp500/*.jsonl.gz"))
        if remote:
            try:
                payloads.append(landing_reader.read(remote[-1]))
            except (OSError, ValueError):
                return {}

    out: dict[str, str] = {}
    for payload in payloads:
        for line in gzip.decompress(payload).decode("utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    out[str(row["symbol"])] = str(row.get("sector", ""))
                except (json.JSONDecodeError, KeyError):
                    continue
    return out


def _main() -> None:
    rows, symbols = build()
    print(f"us panel: {rows:,} rows across {symbols} symbols -> {PANEL_PATH}")


if __name__ == "__main__":
    _main()
