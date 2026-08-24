"""Crypto and mutual fund history, as panel rows the engine already understands.

### What this is, and what it is not

ADR-037 says the real fix is a `MarketView` that can carry a minute candle and
is keyed on an instrument id rather than a symbol. **This is not that.** It is
the cheaper move that unlocks most of the value: resample the landed data to
*daily* bars shaped like `PanelRow`, at which point every existing feature,
both engines, the cost model and the whole validation battery work on crypto
and mutual funds without a line of change.

The distinction matters and is not a technicality:

- **What this unlocks** — any daily cross-sectional strategy on crypto or
  funds. Momentum, reversal, low-volatility, the composites. That is three of
  the ten published strategies and the great majority of what the literature
  actually tests.
- **What it does not** — anything reading a bar shorter than a day. Tweezer
  still cannot be a `Strategy`, and a minute-level crypto strategy still has
  nowhere to live. Those need the real ADR-037 fix.

Resampling 52.5M minute candles to ~1,800 daily bars per symbol discards
almost everything, and that is the point: the daily bar is what a daily
strategy is entitled to see. Keeping the minutes around would only invite a
strategy to read them.

### Crypto has no trading calendar and funds have too much of one

Crypto trades every day including weekends, so its "trading days" are simply
every day with data. Mutual funds publish a NAV on business days only, and
different schemes skip different days — a fund suspended for a week leaves a
gap that is real, not missing data.

Neither matches the NSE calendar, so neither is forced onto it. The panel is
whatever days the data actually has, which is what `trading_days()` derives
anyway.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from eulerlab.features.panel import PanelRow
from eulerlab.ingest import amfi, crypto, landing_reader


def crypto_daily(
    symbols: list[str] | None = None,
    *,
    directory: Path | None = None,
    start: date | None = None,
) -> list[PanelRow]:
    """Daily bars for the landed crypto universe.

    Turnover is `close * volume` — the quote-currency value traded, which is
    what `turnover_liquidity` and `illiquidity_amihud` expect. Binance also
    publishes a quote-volume column, and it is deliberately not used: deriving
    turnover the same way the equity panel does keeps one definition across
    asset classes rather than two that nearly agree.
    """
    root = directory or crypto.LANDING
    # The directory is the fallback, not the source of truth. `prune-local`
    # moves landed months to B2 and leaves the tree empty, so reading only the
    # disk returned nothing at all — a landed archive of 1,200 symbol-months
    # reported as no crypto data. The same defect the catalog had, one layer
    # down. An explicit `directory=` still wins, because the tests pass one.
    if directory is None:
        listed = landing_reader.available("crypto", "*/*.jsonl.gz")
        names = {r.split("/")[1] for r in listed if len(r.split("/")) >= 3}
        if names:
            wanted = set(symbols) & names if symbols else names
            return _crypto_from_cloud(sorted(wanted), start)

    if not root.exists():
        return []

    wanted = set(symbols) if symbols else {p.name for p in root.iterdir() if p.is_dir()}
    rows: list[PanelRow] = []

    for symbol in sorted(wanted):
        folder = root / symbol
        if not folder.is_dir():
            continue

        # (open, high, low, close, volume) accumulated per day.
        days: dict[date, list[float]] = {}
        for path in sorted(folder.glob("*.jsonl.gz")):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        when = datetime.fromisoformat(str(row["event_time"])).date()
                        if start and when < start:
                            continue
                        close = float(row["close"])
                        entry = days.get(when)
                        if entry is None:
                            days[when] = [
                                float(row["open"]),
                                float(row["high"]),
                                float(row["low"]),
                                close,
                                float(row["volume"]),
                            ]
                        else:
                            entry[1] = max(entry[1], float(row["high"]))
                            entry[2] = min(entry[2], float(row["low"]))
                            entry[3] = close  # last close of the day wins
                            entry[4] += float(row["volume"])
            except Exception:
                # A month that cannot be read is skipped, not fatal. One
                # damaged file must not cost the other 1,199.
                continue

        for when, (open_, high, low, close, volume) in sorted(days.items()):
            rows.append(
                PanelRow(
                    day=when,
                    symbol=symbol,
                    close=close,
                    volume=volume,
                    turnover=close * volume,
                    isin=f"CRYPTO:{symbol}",
                    open=open_,
                    high=high,
                    low=low,
                )
            )
    return rows


def fund_daily(
    *,
    directory: Path | None = None,
    start: date | None = None,
    direct_growth_only: bool = True,
    limit: int = 0,
) -> list[PanelRow]:
    """Daily NAV series for mutual fund schemes, as panel rows.

    **Volume and turnover are zero, and that is not a placeholder.** A mutual
    fund has no traded volume — units are created and redeemed at NAV, not
    matched in a book. Any feature reading turnover (`turnover_liquidity`,
    `illiquidity_amihud`, `volume_trend`) is therefore meaningless here and
    will return nothing rather than a number, which is the correct behaviour:
    a liquidity factor on an instrument with no market is not a small effect,
    it is a category error.

    `direct_growth_only` because a regular plan differs from its direct twin
    only by commission, and a payout option differs by cash leaving the NAV.
    Including all three would triple the cross-section with near-duplicates
    and make any rank meaningless.
    """
    root = directory or amfi.HISTORY_DIR
    if not root.exists():
        return []

    keep: set[str] | None = None
    if direct_growth_only:
        try:
            keep = {s.scheme_code for s in amfi.fetch_universe() if s.is_direct_growth}
        except Exception:
            # No network: fall back to every landed scheme rather than none.
            keep = None

    # Filter FIRST, then limit. Taking the alphabetical head and filtering
    # afterwards samples nothing: AMFI scheme codes are issued in order, direct
    # plans only became mandatory in 2013, so every direct-growth scheme sits at
    # the HIGH end of the range. `limit=600` over a sorted list returned exactly
    # zero of them — a biased sample that looked like an empty dataset.
    files = sorted(root.glob("*.jsonl.gz"))
    if keep is not None:
        files = [p for p in files if p.name.split(".")[0] in keep]
    if limit:
        files = files[:limit]

    rows: list[PanelRow] = []
    for path in files:
        code = path.name.split(".")[0]
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    when = date.fromisoformat(str(row["event_time"]))
                    if start and when < start:
                        continue
                    nav = float(row["nav"])
                    if nav <= 0:
                        continue
                    rows.append(
                        PanelRow(
                            day=when,
                            symbol=code,
                            close=nav,
                            volume=0.0,
                            turnover=0.0,
                            isin=f"MF:{code}",
                        )
                    )
        except Exception:
            continue

    rows.sort(key=lambda r: (r.day, r.symbol))
    return rows


def coverage(rows: list[PanelRow]) -> dict[str, object]:
    """What a built panel actually contains, for a report that cannot flatter."""
    if not rows:
        return {"rows": 0, "symbols": 0, "days": 0, "first": None, "last": None}
    per_symbol: dict[str, int] = defaultdict(int)
    for row in rows:
        per_symbol[row.symbol] += 1
    days = {r.day for r in rows}
    return {
        "rows": len(rows),
        "symbols": len(per_symbol),
        "days": len(days),
        "first": min(days).isoformat(),
        "last": max(days).isoformat(),
        "thinnest": min(per_symbol.values()),
        "fattest": max(per_symbol.values()),
    }


def fx_daily(
    pairs: list[str] | None = None,
    *,
    directory: Path | None = None,
    start: date | None = None,
) -> list[PanelRow]:
    """Daily bars for the landed FX universe, from minute bars.

    ### Volume and turnover are zero, and that is a fact rather than a gap

    Spot FX has no central exchange and therefore no consolidated volume. FXCM
    publishes none, and a tick count from Dukascopy measures how often *one
    broker* updated a quote, which is not turnover in any sense the liquidity
    features mean. Reporting zero keeps `turnover_liquidity` and
    `illiquidity_amihud` from producing a ranking out of an artefact — those
    features simply cannot be used here, and a fabricated denominator would
    hide that rather than state it.

    ### The spread is the cost model

    Every other asset class in this repository pays exchange charges, STT and
    stamp duty. FX pays none of them: the cost of trading it *is* the bid-ask
    spread. That is measured per minute in the landed data, so the daily row
    carries the **median** of the day's spreads — median rather than mean
    because the distribution has a long right tail at the Sunday open and
    around releases, and a mean would charge every trade for the worst minutes
    of the week.
    """
    from eulerlab.ingest import fx

    if directory is not None:
        # An explicit directory means a test or a one-off; the cloud is not
        # consulted, because a test that silently reached the network would be
        # measuring something other than what it thinks.
        return _fx_from_disk(directory, pairs, start)

    paths = landing_reader.available("fx", "*/*/*.jsonl.gz")
    if not paths:
        return []

    wanted = set(pairs) if pairs else None
    rows: list[PanelRow] = []
    for relative in paths:
        pair = relative.split("/")[1]
        if wanted is not None and pair not in wanted:
            continue
        try:
            payload = landing_reader.read(relative)
            bars = [
                fx.Bar.from_row(json.loads(line))
                for line in gzip.decompress(payload).decode("utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError, KeyError, EOFError):
            continue
        row = _fx_row(pair, bars, start)
        if row is not None:
            rows.append(row)

    rows.sort(key=lambda row: (row.day, row.symbol))
    return rows


def _fx_row(pair: str, bars: Sequence[object], start: date | None) -> PanelRow | None:
    """One day of FX minute bars as a panel row, or None if it is unusable."""
    from eulerlab.ingest import fx as fx_mod

    typed = [b for b in bars if isinstance(b, fx_mod.Bar)]
    if not typed:
        return None
    day = typed[0].ts.date()
    if start and day < start:
        return None

    # Median, and floored at zero. See the docstring on `fx_daily`: roughly
    # 2.8% of source minutes are crossed, and a negative cost would pay a
    # strategy to trade.
    spreads = sorted(bar.mean_spread for bar in typed)
    return PanelRow(
        day=day,
        symbol=pair,
        close=typed[-1].close,
        volume=0.0,
        turnover=0.0,
        isin=f"FX:{pair}",
        spread=max(0.0, spreads[len(spreads) // 2]),
        open=typed[0].open,
        high=max(bar.high for bar in typed),
        low=min(bar.low for bar in typed),
    )


def _crypto_from_cloud(symbols: list[str], start: date | None) -> list[PanelRow]:
    """Daily bars built from the landed archive, fetched from B2 when pruned.

    Same aggregation as the on-disk path — last close of the day wins, volume
    sums, turnover is close x volume - deliberately duplicated rather than
    shared, because the two differ only in how bytes arrive and merging them
    behind a flag made the disk path harder to read for no gain.

    Only months that could straddle `start` are opened. The archive is 1,200
    symbol-months; fetching all of them to answer a ten-day question would
    trade one bug for a slower one.
    """
    rows: list[PanelRow] = []
    listed = landing_reader.available("crypto", "*/*.jsonl.gz")
    by_symbol: dict[str, list[str]] = {}
    for relative in listed:
        parts = relative.split("/")
        if len(parts) >= 3 and parts[1] in set(symbols):
            by_symbol.setdefault(parts[1], []).append(relative)

    cutoff = f"{start:%Y-%m}" if start else ""
    for symbol in symbols:
        days: dict[date, list[float]] = {}
        for relative in sorted(by_symbol.get(symbol, [])):
            # Filenames carry the month, so a month entirely before `start` is
            # skipped without being downloaded. Matched rather than sliced: the
            # first version took `[-15:-9]` and got "026-07", which sorted below
            # every real cutoff and skipped the entire archive.
            stamp = re.search(r"(\d{4}-\d{2})\.jsonl\.gz$", relative)
            if cutoff and stamp and stamp.group(1) < cutoff:
                continue
            try:
                payload = gzip.decompress(landing_reader.read(relative))
            except Exception:
                continue
            for line in payload.decode("utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    when = datetime.fromisoformat(str(row["event_time"])).date()
                    if start and when < start:
                        continue
                    close = float(row["close"])
                    entry = days.get(when)
                    if entry is None:
                        days[when] = [
                            float(row["open"]),
                            float(row["high"]),
                            float(row["low"]),
                            close,
                            float(row["volume"]),
                        ]
                    else:
                        entry[1] = max(entry[1], float(row["high"]))
                        entry[2] = min(entry[2], float(row["low"]))
                        entry[3] = close
                        entry[4] += float(row["volume"])
                except Exception:
                    continue

        for when, (open_, high, low, close, volume) in sorted(days.items()):
            rows.append(
                PanelRow(
                    day=when,
                    symbol=symbol,
                    close=close,
                    volume=volume,
                    turnover=close * volume,
                    isin=f"CRYPTO:{symbol}",
                    open=open_,
                    high=high,
                    low=low,
                )
            )
    return rows


def _fx_from_disk(directory: Path, pairs: list[str] | None, start: date | None) -> list[PanelRow]:
    """The local-only path, for tests and explicit directories."""
    from eulerlab.ingest import fx as fx_mod

    if not directory.exists():
        return []
    wanted = set(pairs) if pairs else {p.name for p in directory.iterdir() if p.is_dir()}
    rows: list[PanelRow] = []
    for pair in sorted(wanted):
        folder = directory / pair
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*/*.jsonl.gz")):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    bars = [
                        fx_mod.Bar.from_row(json.loads(line)) for line in handle if line.strip()
                    ]
            except (OSError, ValueError, KeyError, EOFError):
                continue
            row = _fx_row(pair, list(bars), start)
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda row: (row.day, row.symbol))
    return rows
