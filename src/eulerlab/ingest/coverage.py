"""What data the platform holds, up to which day, and what is missing.

The Instruments page could search instruments but could not answer "is
everything here up to today?". On 2026-10-08 the bhavcopy had landed and the
paper books still showed 7 Oct, and nothing on any page said so (T-4030).

One row per dataset: the last day held, the day it should reach by now, how
many sessions it is behind, and what fixes it. Read from files that are
already local — the NSE manifest, the derived tables' last lines, the landing
census, the paper states — so the page answers in well under a second and
never lists the bucket.

### What "should reach" means

- **nse** — the latest NSE session, counting today from 15:31 IST, one minute
  after the close (ADR-079). A session is a weekday that is not a closure, or a
  weekend day NSE traded (Muhurat, special Saturdays). Closures are the past
  days with no bhavcopy plus NSE's published holiday list (`make holidays`, the
  current year), so a scheduled holiday such as 10 Nov 2026 is not expected
  even before the next session lands. Until today's file lands the row reads
  **missing**, not "behind": the operator asked to see the gap from the close,
  and `make india-live` is retrying it. A weekend session is known only once
  its file has landed; NSE's list does not announce them.
- **amfi** — mutual fund NAVs are published late in the evening: the previous
  weekday.
- **us** — the latest New York weekday, from 18:00 New York. US holidays are
  not known here, so one reads as one session behind.
- **crypto** — Binance publishes each UTC day's archive the next day: yesterday,
  UTC.
- **weekly** — FX candles come in weekly files: up to 10 days old is current.
- **info** — shown with its last day but no expectation (fundamentals refresh
  over an hour, overnight; option chain snapshots exist only in market hours).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.paths import data_path

IST = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")

LANDING = data_path("landing")
DERIVED = data_path("derived")
DEPLOYMENTS = data_path("deployments")

UPDATE = "Tools → Instruments → Update all data"


@dataclass(frozen=True)
class Row:
    group: str
    name: str
    last: str
    expected: str
    behind: int
    status: str
    """ok · behind (one session) · stale (two or more) · missing · info"""
    detail: str
    fix: str
    steps: tuple[str, ...] = ()
    """The feed steps that bring this dataset up to date, in run order —
    what its own Update button runs. Empty where no button can (Kite minute
    bars need a login; fundamentals take hours)."""


# --- reading the last day cheaply ---------------------------------------------


def last_line(path: Path, *, chunk: int = 1 << 16) -> str:
    """The last non-empty line of a file, read from the end.

    The price panel is 745 MB; reading it to learn its last day would take
    seconds on every page load.
    """
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        buf = b""
        pos = end
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            handle.seek(pos)
            buf = handle.read(step) + buf
            lines = [x for x in buf.split(b"\n") if x.strip()]
            if len(lines) >= 2 or (pos == 0 and lines):
                return lines[-1].decode("utf-8")
    return ""


def last_day_jsonl(path: Path, field: str = "d") -> str:
    line = last_line(path)
    if not line:
        return ""
    try:
        value = json.loads(line).get(field, "")
    except json.JSONDecodeError:
        return ""
    return str(value)


_MAX_DAY_CACHE: dict[str, tuple[int, str]] = {}


def max_day_jsonl(path: Path) -> str:
    """The latest `"d"` day anywhere in a JSONL table, cached by mtime.

    The market-history tables (index history, delivery, Nifty futures) are
    extended, not rebuilt: a backfilled older day (a weekend special session,
    the 2000-2014 history) is appended after the newest one, so their last line
    is not their last day. Reading the last line made the Data page show
    "2941 behind" for all three on 2026-11-15 (HISTORY, same date).
    """
    if not path.exists():
        return ""
    stamp = path.stat().st_mtime_ns
    cached = _MAX_DAY_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    best = ""
    key = b'"d":'
    with path.open("rb") as handle:
        for line in handle:
            at = line.find(key)
            if at < 0:
                continue
            start = line.find(b'"', at + len(key))
            if start < 0:
                continue
            day = line[start + 1 : start + 11].decode("ascii", "replace")
            if len(day) == 10 and day[4] == "-" and day > best:
                best = day
    _MAX_DAY_CACHE[str(path)] = (stamp, best)
    return best


_SCAN_CACHE: dict[tuple[str, str], tuple[int, dict[str, str]]] = {}


def _max_by(path: Path, group: str, value: str, *, nonempty: bool = False) -> dict[str, str]:
    """`{group value: max(value)}` across a JSONL manifest, cached by mtime."""
    if not path.exists():
        return {}
    stamp = path.stat().st_mtime_ns
    key = (str(path), f"{group}|{value}|nonempty={nonempty}")
    cached = _SCAN_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if nonempty and int(row.get("rows", 0)) <= 0:
                continue
            g = str(row.get(group, "")) if group else ""
            v = str(row.get(value, ""))
            if v and v > out.get(g, ""):
                out[g] = v
    _SCAN_CACHE[key] = (stamp, out)
    return out


def _local_latest(tree: str, pattern: str) -> str:
    from eulerlab.ingest.manifest import latest_date

    root = LANDING / tree
    if not root.exists():
        return ""
    # Sliced, not `Path.relative_to`: every glob result is under `root`, and
    # 3,674 `relative_to` calls were most of this table's 0.16 s.
    cut = len(str(root)) + 1
    return latest_date(str(p)[cut:] for p in root.glob(pattern))


def _census_latest(key: str) -> str:
    from eulerlab.ingest import manifest

    loaded = manifest.load()
    census = loaded.census(key) if loaded else None
    return census.latest if census else ""


# --- what each cadence should have reached -------------------------------------


def is_nse_session(
    day: date, closed: frozenset[date], extra: frozenset[date] = frozenset()
) -> bool:
    """A weekday that is not a closure, or a weekend day NSE traded."""
    return day in extra or (day.weekday() < 5 and day not in closed)


def _weekday_back(day: date, closed: frozenset[date], extra: frozenset[date] = frozenset()) -> date:
    while not is_nse_session(day, closed, extra):
        day -= timedelta(days=1)
    return day


NSE_DUE = (15, 31)
"""One minute after the cash close (ADR-079). Was 19:00, when the files are
usually out; the operator wants the gap shown from the close instead."""


# ASSUMPTION: A-051 — the cut-off times below are observed, not published.
def expected_nse(
    now: datetime, closed: frozenset[date], extra: frozenset[date] = frozenset()
) -> date:
    ist = now.astimezone(IST)
    day = ist.date() if (ist.hour, ist.minute) >= NSE_DUE else ist.date() - timedelta(days=1)
    return _weekday_back(day, closed, extra)


def expected_amfi(now: datetime, closed: frozenset[date]) -> date:
    return _weekday_back(now.astimezone(IST).date() - timedelta(days=1), frozenset())


def expected_us(now: datetime, closed: frozenset[date]) -> date:
    ny = now.astimezone(NEW_YORK)
    day = ny.date() if ny.hour >= 18 else ny.date() - timedelta(days=1)
    return _weekday_back(day, frozenset())


def expected_crypto(now: datetime, closed: frozenset[date]) -> date:
    return now.astimezone(UTC).date() - timedelta(days=1)


EXPECTED: dict[str, Callable[[datetime, frozenset[date]], date]] = {
    "nse": expected_nse,
    "amfi": expected_amfi,
    "us": expected_us,
    "crypto": expected_crypto,
}


def sessions_behind(
    last: date,
    expected: date,
    cadence: str,
    closed: frozenset[date],
    extra: frozenset[date] = frozenset(),
) -> int:
    """Sessions in (last, expected] for this cadence."""
    if last >= expected:
        return 0
    count, day = 0, last
    while day < expected:
        day += timedelta(days=1)
        if cadence == "crypto":
            count += 1
        elif cadence == "nse":
            count += is_nse_session(day, closed, extra)
        elif day.weekday() < 5:
            count += 1
    return count


def judge(*, steps: tuple[str, ...] = (), **kw: Any) -> Row:
    """One row: compare `last` against what `cadence` should have reached."""
    return replace(_grade(**kw), steps=steps)


def _grade(
    *,
    group: str,
    name: str,
    last: str,
    cadence: str,
    now: datetime,
    closed: frozenset[date],
    detail: str = "",
    fix: str = UPDATE,
    extra: frozenset[date] = frozenset(),
) -> Row:
    if not last:
        return Row(group, name, "", "", 0, "missing", detail or "nothing held", fix)
    if cadence == "info":
        return Row(group, name, last, "", 0, "info", detail, fix)
    last_day = _as_day(last)
    if cadence == "weekly":
        age = (now.astimezone(UTC).date() - last_day).days
        status = "ok" if age <= 10 else "behind" if age <= 17 else "stale"
        return Row(group, name, last, "within 10 days", 0, status, detail, fix)
    if cadence == "nse":
        expected = expected_nse(now, closed, extra)
    else:
        expected = EXPECTED[cadence](now, closed)
    behind = sessions_behind(last_day, expected, cadence, closed, extra)
    status = "ok" if behind == 0 else "behind" if behind == 1 else "stale"
    if cadence == "nse" and behind == 1 and expected == now.astimezone(IST).date():
        # Only today's session is absent: due since 15:31 and not in yet.
        status = "missing"
        detail = f"today's data not in yet{'; ' + detail if detail else ''}"
    return Row(group, name, last, expected.isoformat(), behind, status, detail, fix)


def _as_day(text: str) -> date:
    """A `YYYY-MM-DD`, or a `YYYY-MM` month read as its last day held."""
    if len(text) == 7:
        first = date.fromisoformat(f"{text}-01")
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    return date.fromisoformat(text[:10])


def _calendar(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _days(raw: dict[str, Any], key: str) -> frozenset[date]:
    return frozenset(date.fromisoformat(d) for d in raw.get(key, []))


def nse_closures(
    path: Path = DERIVED / "nse_calendar.json",
    reference: Path = LANDING / "reference",
) -> frozenset[date]:
    """Days NSE is shut: past days with no bhavcopy, plus NSE's published list.

    The published list (`make holidays`) is what makes a holiday that has not
    happened yet, or happened today, known (T-3998). A listed day that has a
    landed bhavcopy traded anyway (a Muhurat session falls on a listed
    holiday), so it is never a closure.
    """
    from eulerlab.ingest.holidays import load_holidays

    raw = _calendar(path)
    return (_days(raw, "holidays") | load_holidays(reference)) - _days(raw, "trading_days")


def nse_weekend_sessions(path: Path = DERIVED / "nse_calendar.json") -> frozenset[date]:
    """Saturdays and Sundays NSE traded, from landed bhavcopies (research 183)."""
    return _days(_calendar(path), "weekend_sessions")


# --- the table -----------------------------------------------------------------

_EOD = "NSE end-of-day"
_FILES = "NSE index closes and delivery"
PAPER_STEPS: tuple[str, ...] = (_EOD, "price panel", "paper books")

STEPS_FOR: dict[str, tuple[str, ...]] = {
    "Cash bhavcopy": (_EOD,),
    "F&O bhavcopy": (_EOD,),
    "Participant OI": ("participant OI",),
    "Index closes (incl. VIX)": (_FILES,),
    "Delivery positions": (_FILES,),
    "FII/DII cash flows": ("FII/DII cash flows",),
    "Price panel": (_EOD, "price panel"),
    "Index history": (_FILES, "market history"),
    "Delivery table": (_FILES, "market history"),
    "Nifty futures": (_EOD, "market history"),
    "Nifty options": (_EOD, "Nifty options"),
    "US daily panel": ("US bars and actions", "US panel"),
    "Crypto 1-minute": ("crypto gap",),
    "FX 1-minute": ("FX",),
    "Mutual fund NAVs": ("mutual fund NAVs",),
    "Option chain snapshots": ("option chain",),
    "India minute bars (Kite/Angel)": ("India minute bars",),
    "MCX iCOMDEX minute bars (Kite)": ("MCX index minute bars",),
}
"""Each dataset's own Update button: the fetch it derives from, then the build.
Every name must be a `daily_feed.STEPS` name (tests/test_data_pipeline.py)."""


def _paper_rows(
    now: datetime, closed: frozenset[date], extra: frozenset[date] = frozenset()
) -> Iterable[Row]:
    if not DEPLOYMENTS.exists():
        return
    for folder in sorted(DEPLOYMENTS.iterdir()):
        spec_path, state_path = folder / "deployment.json", folder / "state.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if spec.get("status") != "active":
            continue
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        # The money put in now (capital plus applied flows), as Live & Risk
        # counts it; the starting capital alone went stale after a deposit.
        put_in = float(spec.get("capital", 0)) + sum(
            float(flow.get("amount") or 0)
            for flow in state.get("flows") or []
            if flow.get("applied_day")
        )
        row = judge(
            group="Paper trading",
            name=f"{spec.get('strategy_id')} · ₹{put_in:,.0f} in",
            last=str(state.get("traded_through") or ""),
            cadence="nse",
            now=now,
            closed=closed,
            extra=extra,
            detail=f"{state.get('status', 'not run')} — {spec.get('id')}",
            steps=PAPER_STEPS,
        )
        # A deployment younger than two sessions has nothing to trade yet; that
        # is waiting, not stale.
        if state.get("status") == "waiting":
            row = Row(**{**asdict(row), "status": "info", "detail": str(state.get("reason"))})
        yield row


def table(now: datetime | None = None) -> list[Row]:
    now = now or datetime.now(UTC)
    closed = nse_closures()
    extra = nse_weekend_sessions()
    nse = _max_by(LANDING / "nse" / "manifest.jsonl", "segment", "trade_date")
    rows: list[Row] = []

    def add(group: str, name: str, last: str, cadence: str, **kw: Any) -> None:
        rows.append(
            judge(
                group=group,
                name=name,
                last=last,
                cadence=cadence,
                now=now,
                closed=closed,
                extra=extra,
                steps=STEPS_FOR.get(name, ()),
                **kw,
            )
        )

    from eulerlab.ingest.provisional_daily import standing_days

    due = expected_nse(now, closed, extra).isoformat()
    stand_in = standing_days().get(due, 0)
    kite = _max_by(LANDING / "kite_minute" / "manifest.jsonl", "", "end", nonempty=True).get("", "")
    cash_detail = "every NSE equity, daily"
    if nse.get("cm", "") < due:
        cash_detail = (
            f"provisional bars from minute data for {stand_in} stocks until it lands"
            if stand_in
            else "no minute bars for today either"
            if kite < due
            else "minute bars in, session not complete yet"
        )

    landed = "NSE files (landed)"
    add(landed, "Cash bhavcopy", nse.get("cm", ""), "nse", detail=cash_detail)
    add(landed, "F&O bhavcopy", nse.get("fo", ""), "nse", detail="every derivative, daily")
    add(landed, "Participant OI", nse.get("participant_oi", ""), "nse")
    add(landed, "Index closes (incl. VIX)", nse.get("indices", ""), "nse")
    add(landed, "Delivery positions", nse.get("delivery", ""), "nse")
    flows = _max_by(LANDING / "fii_dii" / "manifest.jsonl", "segment", "trade_date")
    add(
        landed,
        "FII/DII cash flows",
        flows.get("cash", ""),
        "nse",
        detail="NSE serves the latest day only: a day not captured that evening is lost",
    )

    built = "Built for research and trading"
    add(
        built,
        "Price panel",
        last_day_jsonl(DERIVED / "price_panel.jsonl"),
        "nse",
        detail="what backtests and paper trading read",
    )
    add(built, "Index history", max_day_jsonl(DERIVED / "index_history.jsonl"), "nse")
    add(built, "Delivery table", max_day_jsonl(DERIVED / "delivery.jsonl"), "nse")
    add(built, "Nifty futures", max_day_jsonl(DERIVED / "nifty_futures.jsonl"), "nse")
    add(built, "Nifty options", last_day_jsonl(DERIVED / "nifty_options.jsonl"), "nse")
    add(built, "US daily panel", last_day_jsonl(DERIVED / "us_panel.jsonl"), "us")

    rows.extend(_paper_rows(now, closed, extra))

    other = "Other markets (landed)"
    add(
        other,
        "Crypto 1-minute",
        max(_census_latest("crypto"), _local_latest("crypto", "*/*.jsonl.gz")),
        "crypto",
    )
    add(
        other,
        "FX 1-minute",
        max(_census_latest("fx"), _local_latest("fx", "*/*/*.jsonl.gz")),
        "weekly",
    )
    add(
        other,
        "Mutual fund NAVs",
        max(_census_latest("mf/navall"), _local_latest("mf", "navall/*.jsonl.gz")),
        "amfi",
    )

    slow = "Not in the button"
    # Without a Kite token the step fetches from Angel One into the same store
    # (2026-11-09), so one manifest says how far the minute bars reach.
    add(
        "Minute bars (Kite/Angel)",
        "India minute bars (Kite/Angel)",
        kite,
        "nse",
        detail=(
            "daily bhavcopy is in; minute bars come from Kite, or Angel One without a Kite login"
            if kite < due <= nse.get("cm", "")
            else "Kite, or Angel One when there is no Kite login"
        ),
        fix="Update (Angel One fills in without a Kite login)",
    )
    mcx_indexes = _max_by(
        LANDING / "mcx_indices" / "manifest.jsonl", "symbol", "end", nonempty=True
    )
    mcx_last = max(mcx_indexes.values(), default="")
    add(
        "Needs a Kite login",
        "MCX iCOMDEX minute bars (Kite)",
        mcx_last,
        "nse",
        detail=(
            f"{len(mcx_indexes)} index series landed; Kite history is partial and the "
            "full five-year window was queried, including empty history ranges"
        ),
        fix="Log in to Kite on this page, then Update",
    )
    funda = _max_by(LANDING / "fundamentals" / "manifest.jsonl", "", "fetch_date").get("", "")
    add(
        slow,
        "Fundamentals",
        funda,
        "info",
        detail="walks every symbol for hours; runs at the end of make daily",
        fix="make daily",
    )
    chain = _local_latest("option_chain", "*/*")
    add(
        slow,
        "Option chain snapshots",
        chain,
        "info",
        detail="bid/ask exists only in market hours; the button takes one if open",
    )
    return rows


def summary(rows: list[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[row.status] = out.get(row.status, 0) + 1
    return out


def main() -> int:
    """`make coverage`: the Instruments table, in a terminal."""
    rows = table()
    group = ""
    for row in rows:
        if row.group != group:
            group = row.group
            print(f"\n{group}")
        fix = f"  → {row.fix}" if row.status not in ("ok", "info") else ""
        print(f"  {row.status:8s} {row.name:40s} {row.last or '—':11s} {row.expected:14s}{fix}")
    counts = summary(rows)
    print("\n" + " · ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    return 1 if counts.get("stale") or counts.get("missing") else 0


if __name__ == "__main__":
    raise SystemExit(main())
