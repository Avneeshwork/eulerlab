"""Rescale Angel One's old minute bars to Kite's price level (research 193).

Kite and Angel adjust history differently: RELIANCE's 15:29 close on
2021-08-20 is 1,020.00 at Kite and 1,074.13 at Angel. The operator chose
(2026-11-13) to rescale Angel to Kite using the days both vendors cover.

The overlap is `CALIBRATION`, Kite's first weeks (Angel's bars for it are
fetched by `make angel-history FROM=2021-08-19 TO=2021-09-15`). Per symbol:

- **factor**: the median of Kite close / Angel close over every minute both hold;
- **drift**: over Kite's first `SEAM_DAYS` sessions, the largest gap between
  one day's median ratio and the factor (their median). A pure adjustment
  difference is one constant, so a drift above `MAX_DRIFT` means the two
  vendors are not the same series there and the symbol is refused;
- **seam**: the return from Angel's last session before Kite's start, scaled,
  to Kite's first close, against the same return in NSE's bhavcopy panel
  (unadjusted, and no corporate action falls between those two days). A miss
  above `MAX_SEAM` refuses the symbol: that is the false jump the rescale
  exists to remove;
- **volume factor**: the median of daily Kite volume / Angel volume.

The factors are written to `FACTORS` with each symbol's checks; the minute
reader (`intraday/store.fetch(history=True)`) uses only symbols that passed.
Raw bars are never edited.

`make angel-rescale`.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from eulerlab.intraday.tweezer import Candle
from eulerlab.paths import data_path

CALIBRATION = (date(2021, 8, 19), date(2021, 9, 15))
SEAM_BEFORE = date(2021, 8, 18)
"""Angel's last session before Kite's first (19 Aug 2021 was a holiday, Muharram)."""
FACTORS = data_path("derived/angel_minute_factors.json")
PANEL = data_path("derived/price_panel.jsonl")
MAX_DRIFT = 0.005
"""Half a percent: one vendor's day ratio may wander this far from the factor."""
MAX_SEAM = 0.005
"""Half a percent: the scaled seam return, close to close as `closing_price`
rebuilds NSE's close, may miss the bhavcopy's return by this much."""
MIN_DAYS = 5
SEAM_DAYS = 3
"""The factor is the ratio on Kite's first three sessions, the ones next to the
seam. The first run (2026-11-13) took the whole window and refused eight
symbols, POWERGRID by 33%, because a bonus or a large dividend inside the
window moved one vendor's ratio and not the other's."""


@dataclass(frozen=True)
class Factor:
    symbol: str
    factor: float
    volume_factor: float
    days: int
    drift: float
    seam_return: float | None
    bhav_return: float | None
    status: str
    """"ok", or why the symbol gets no history."""
    later_move: float = 0.0
    """The largest move of a day's ratio across the whole window. Not a check: a
    corporate action inside the window (POWERGRID's 2021 bonus) moves it, and
    only the ratio at the seam matters."""
    note: str = ""

    def apply(self, candle: Candle) -> Candle:
        f = self.factor
        return replace(
            candle,
            open=candle.open * f,
            high=candle.high * f,
            low=candle.low * f,
            close=candle.close * f,
            volume=candle.volume * self.volume_factor,
        )


def _by_day(candles: Iterable[Candle]) -> dict[date, list[Candle]]:
    out: dict[date, list[Candle]] = {}
    for c in candles:
        out.setdefault(c.ts.date(), []).append(c)
    return out


def closing_price(day: Sequence[Candle]) -> float:
    """NSE's close as minute bars can rebuild it: the volume-weighted price of the
    last half hour (15:00 on), which is how NSE set the close before the 2026
    closing auction. A bar's close stands in for its trades. The last close when
    nothing traded then. Comparing a raw last-minute close against the
    bhavcopy missed by up to 1.2% on 13 Nov 2026's first run (ABB)."""
    tail = [c for c in day if (c.ts.hour, c.ts.minute) >= (15, 0) and c.volume > 0]
    volume = sum(c.volume for c in tail)
    if not volume:
        return max(day, key=lambda c: c.ts).close
    return sum(c.close * c.volume for c in tail) / volume


def measure(
    symbol: str,
    kite: Sequence[Candle],
    angel: Sequence[Candle],
    angel_before: Sequence[Candle],
    bhav: dict[date, float],
) -> Factor:
    """One symbol's factor and its checks, from candles already read."""
    a_close = {c.ts: c.close for c in angel if c.close > 0}
    ratios: dict[date, list[float]] = {}
    for c in kite:
        other = a_close.get(c.ts)
        if other and c.close > 0:
            ratios.setdefault(c.ts.date(), []).append(c.close / other)
    days = len(ratios)
    if days < MIN_DAYS:
        return Factor(symbol, 0.0, 0.0, days, 0.0, None, None, f"only {days} overlap days")
    seam_days = sorted(ratios)[:SEAM_DAYS]
    factor = statistics.median(r for d in seam_days for r in ratios[d])
    drift = max(abs(statistics.median(ratios[d]) / factor - 1) for d in seam_days)
    later = max(abs(statistics.median(v) / factor - 1) for v in ratios.values())

    k_days, a_days = _by_day(kite), _by_day(angel)
    vol = [
        sum(c.volume for c in k_days[d]) / sum(c.volume for c in a_days[d])
        for d in seam_days
        if d in a_days and sum(c.volume for c in a_days[d]) > 0
    ]
    volume_factor = statistics.median(vol) if vol else 1.0

    before = _by_day(c for c in angel_before if c.ts.date() <= SEAM_BEFORE)
    first_day = min(k_days)
    seam = bhav_ret = None
    if before:
        last_day = max(before)
        seam = closing_price(k_days[first_day]) / (closing_price(before[last_day]) * factor) - 1
        prev, now = bhav.get(last_day), bhav.get(first_day)
        if prev and now:
            bhav_ret = now / prev - 1
    if drift > MAX_DRIFT:
        status = f"drift {drift:.2%} over {MAX_DRIFT:.1%}"
    elif seam is None:
        status = "no Angel bars before Kite's start"
    elif bhav_ret is None:
        status = "seam unchecked: no bhavcopy close under this symbol"
    elif abs(seam - bhav_ret) > MAX_SEAM:
        status = f"seam {seam:+.2%} against bhavcopy {bhav_ret:+.2%}"
    else:
        status = "ok"
    return Factor(symbol, factor, volume_factor, days, drift, seam, bhav_ret, status, later)


def bhav_closes(
    symbols: set[str], days: set[date], panel: Path = PANEL
) -> dict[str, dict[date, float]]:
    """NSE bhavcopy closes (unadjusted) for `symbols` on `days`.

    Matched by the panel's instrument key (ISIN) as the symbol carries it
    today, so a renamed company (ZOMATO, now ETERNAL) still finds its 2021
    close; by the symbol itself when the panel has no key for it.
    """
    wanted = {f'"d": "{d.isoformat()}"' for d in days}
    key_of: dict[str, str] = {}
    by_key: dict[str, dict[date, float]] = {}
    by_symbol: dict[str, dict[date, float]] = {}
    with panel.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            symbol, key = str(row.get("s", "")), str(row.get("isin", ""))
            if symbol in symbols and key:
                key_of[symbol] = key  # the file runs in date order: the last is today's
            if row.get("c") and any(w in line for w in wanted):
                day = date.fromisoformat(str(row["d"]))
                by_key.setdefault(key, {})[day] = float(row["c"])
                by_symbol.setdefault(symbol, {})[day] = float(row["c"])
    return {
        s: by_key.get(key_of.get(s, ""), {}) or by_symbol.get(s, {})
        for s in symbols
        if by_key.get(key_of.get(s, "")) or by_symbol.get(s)
    }


def load_factors(path: Path = FACTORS) -> dict[str, Factor]:
    """Symbols whose rescale passed its checks. Empty when none is measured."""
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8")).get("symbols", [])
    factors = (Factor(**row) for row in rows)
    return {f.symbol: f for f in factors if f.status == "ok"}


def run(
    symbols: Sequence[str],
    read: Callable[[str, str, date, date], list[Candle]],
    panel: Path = PANEL,
    delisted: frozenset[str] = frozenset(),
) -> list[Factor]:
    """Measure every symbol. `read(tree, symbol, start, end)`; tree is "kite" or "angel"."""
    days = {SEAM_BEFORE, date(2021, 8, 20), date(2021, 8, 17), date(2021, 8, 16)}
    bhav = bhav_closes(set(symbols), days, panel)
    out = []
    for symbol in symbols:
        kite = read("kite", symbol, *CALIBRATION)
        angel = read("angel", symbol, *CALIBRATION)
        before = read("angel", symbol, date(2021, 8, 9), SEAM_BEFORE)
        if not kite and symbol in delisted:
            # No Kite series to join: Angel's bars are the whole history, so
            # there is no seam to break and nothing to scale to.
            out.append(Factor(symbol, 1.0, 1.0, 0, 0.0, None, None, "ok", note="Angel only"))
            continue
        out.append(measure(symbol, kite, angel, before, bhav.get(symbol, {})))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.intraday import store

    parser = argparse.ArgumentParser(prog="angel-rescale", description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    names = sorted(p.name for p in store.HISTORY_CACHE.iterdir() if p.is_dir())
    if args.limit:
        names = names[: args.limit]
    client = store._client()

    def read(tree: str, symbol: str, start: date, end: date) -> list[Candle]:
        if tree == "kite":
            return store._read(symbol, client, store.PREFIX, store.CACHE, start, end)
        return store._read(symbol, client, store.HISTORY_PREFIX, store.HISTORY_CACHE, start, end)

    from eulerlab.ingest.angel_minute import read_delisted

    factors = run(names, read, delisted=frozenset(read_delisted()))
    FACTORS.parent.mkdir(parents=True, exist_ok=True)
    FACTORS.write_text(
        json.dumps(
            {
                "knowledge_time": datetime.now(UTC).isoformat(),
                "calibration": [d.isoformat() for d in CALIBRATION],
                "symbols": [asdict(f) for f in factors],
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    ok = [f for f in factors if f.status == "ok"]
    print(f"angel-rescale: {len(ok)} of {len(factors)} symbols pass; wrote {FACTORS}")
    for f in factors:
        if f.status != "ok":
            print(f"  {f.symbol}: {f.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
