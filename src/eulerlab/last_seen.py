"""The newest prices this machine has already seen, for the dashboard's first paint.

Operator, 2026-10-12: "in dashboard it get last day data initially instead of
last minute bar data and then get live".

The first paint answers from held data so it does not wait on a broker. Held
data used to mean the daily panel alone, so on a Monday afternoon the screen
opened on Friday's moves and then jumped to today's a second later.

Two things can be newer than the panel's last close:

* **The last live quotes.** Every live snapshot already fetches them. `save`
  writes them to one file, replaced whole each time.
* **Held minute bars**, when the minute feed ran after the panel's last day.
  They cover the F&O names only (422 of about 2,350), and the nightly job
  fetches them together with the panel, so on most days they add nothing.

`newest` layers whichever of those postdate the panel, older first, so the
newer one wins where both price a stock. Anything dated on or before the
panel's last day is ignored: the settled close is the better number.

This is one file of the last answer, not a cache with a lifetime. It is never
served in place of a live answer, only before one arrives, and the screen
says what time it is from.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.paths import data_path
from eulerlab.quotes import Quote

IST = ZoneInfo("Asia/Kolkata")
PATH = data_path("derived/last_seen_quotes.json")
MINUTE_ROOT = data_path("landing/kite_minute")

LIVE = "saved live quotes"
MINUTE = "held minute bars"


@dataclass(frozen=True)
class Seen:
    """Returns since the previous close, and when they were true."""

    returns: dict[str, float] = field(default_factory=dict)
    taken_at: str = ""
    """ISO time of the newest layer used. Empty when nothing postdates the panel."""
    sources: tuple[str, ...] = ()


def save(quotes: Mapping[str, Quote], path: Path | None = None) -> None:
    """Replace the file with these quotes. Written whole, then renamed."""
    path = path or PATH
    priced = {s: [q.last, q.previous_close] for s, q in quotes.items() if q.previous_close > 0}
    if not priced:
        return
    taken_at = next(iter(quotes.values())).at
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"taken_at": taken_at, "quotes": priced}), encoding="utf-8")
    os.replace(tmp, path)


def saved(after: date, path: Path | None = None) -> Seen:
    """The saved live quotes, if they were taken on a day after `after`."""
    path = path or PATH
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
        taken_at = str(held["taken_at"])
        taken = datetime.fromisoformat(taken_at)
        quotes = dict(held["quotes"])
    except (OSError, ValueError, KeyError, TypeError):
        # No file, or one cut short by a crash. Either way: nothing seen.
        return Seen()
    if taken.astimezone(IST).date() <= after:
        return Seen()
    returns = {
        str(symbol): float(last) / float(previous) - 1.0
        for symbol, (last, previous) in quotes.items()
        if previous
    }
    return Seen(returns, taken_at, (LIVE,))


def _file_end(path: Path) -> date | None:
    """The end date in a `<start>_<end>.parquet` name."""
    try:
        return date.fromisoformat(path.stem.split("_")[-1])
    except ValueError:
        return None


def minute_bars(after: date, closes: Mapping[str, float], root: Path | None = None) -> Seen:
    """The last held minute bar of each stock, if it is from a day after `after`.

    A file is opened only when its name says it ends after `after`, so on a
    day with nothing newer this reads no file at all.

    The return is measured from the panel's close when the bar's session is
    the first one after it. Otherwise it is measured from the last bar of the
    session before, which is a last trade and not the exchange's closing
    price; a stock with neither is left out.
    """
    root = root or MINUTE_ROOT
    if not root.is_dir():
        return Seen()
    returns: dict[str, float] = {}
    newest = ""
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        fresh = [p for p in folder.glob("*.parquet") if (_file_end(p) or after) > after]
        if not fresh:
            continue
        # Imported here, not above: on most days no file is newer and the
        # first paint should not pay to load a library it will not use.
        import pyarrow.parquet as pq

        # The file ending latest holds the newest bar; ties go to the name
        # that sorts last, which `intraday.store.fetch` also treats as newest.
        table = pq.read_table(
            max(fresh, key=lambda p: (_file_end(p), p.name)), columns=["ts", "close"]
        )
        last_of: dict[date, tuple[str, float]] = {}
        for stamp, close in zip(
            table.column("ts").to_pylist(), table.column("close").to_pylist(), strict=True
        ):
            if close is None:
                continue
            last_of[datetime.fromisoformat(str(stamp)).astimezone(IST).date()] = (
                str(stamp),
                float(close),
            )
        sessions = sorted(last_of)
        if not sessions or sessions[-1] <= after:
            continue
        stamp, last = last_of[sessions[-1]]
        before = sessions[-2] if len(sessions) > 1 else None
        if before is None or before <= after:
            previous = closes.get(folder.name, 0.0)
        else:
            previous = last_of[before][1]
        if previous > 0:
            returns[folder.name] = last / previous - 1.0
            newest = max(newest, stamp)
    if not returns:
        return Seen()
    return Seen(returns, newest, (MINUTE,))


def newest(
    after: date,
    closes: Mapping[str, float],
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> Seen:
    """Everything seen after `after`, the newer source laid over the older."""
    layers = [s for s in (saved(after, path), minute_bars(after, closes, root)) if s.returns]
    if not layers:
        return Seen()
    layers.sort(key=lambda s: datetime.fromisoformat(s.taken_at))
    returns: dict[str, float] = {}
    for layer in layers:
        returns.update(layer.returns)
    return Seen(returns, layers[-1].taken_at, tuple(s.sources[0] for s in layers))
