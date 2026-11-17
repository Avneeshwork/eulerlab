"""Five cash rules from NSE's deal, disclosure, ban and lending reports (research 164).

Pre-registered as H-0093 to H-0097 before any run. The reports were backfilled
from 2021-07-01 (`data/landing/nse_reports`); stock prices and fills come from
research 161's snapshots (`make minute-six`). Trades are 09:20 to 15:10, ₹1
lakh a position, 1x, cash-intraday charges plus 2 bps a side, at most ten a
day, to 2024-11-29.

- **H-0093 / H-0094 bulk deals** (Chaturvedula et al. 2015): one-sided net
  buying on t, buy on t+1; net selling, short. A client on both sides of a
  stock that day is dropped as churn.
- **H-0095 promoter buying**: a SAST promoter acquisition, bought on the first
  session that opens after the disclosure.
- **H-0096 F&O ban entry**: short on the first ban day.
- **H-0097 heavy borrowing** (Boehmer, Jones and Zhang 2008): SLBM quantity x
  price at least 0.5% of 20-session mean traded value, short on t+1.

`make nse-reports-intraday` writes `data/derived/nse_reports_intraday.json`.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cross_section as cs
from eulerlab.strategies.studies import cash_five as five
from eulerlab.strategies.studies import minute_six as six
from eulerlab.strategies.studies import stock_fo as fo

OUT = data_path("derived/nse_reports_intraday.json")
MANIFEST = data_path("landing/nse_reports/manifest.jsonl")
FIRST_DAY = date(2021, 7, 1)
SLBM_SHARE = 0.005
VALUE_DAYS = 20
IST = ZoneInfo("Asia/Kolkata")
"""SAST timestamps are Indian time, written without a zone."""

Fills = list[tuple[date, str, five.Fill]]
Events = dict[str, dict[date, float]]
"""{symbol: {session to trade: ranking score}}."""


# --- reading the reports ---------------------------------------------------------------


def report_files(
    segment: str, first: date = FIRST_DAY, through: date | None = None
) -> Iterator[tuple[date, str]]:
    """(trade date, landing path) for each landed file of one report, in the window."""
    from eulerlab.ingest import landing_reader

    seen = set()
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") != segment or entry["path"] in seen:
            continue
        day = date.fromisoformat(entry["trade_date"])
        if first <= day <= (through or cs.DATA_END):
            seen.add(entry["path"])
            yield (
                day,
                landing_reader.read(f"nse_reports/{entry['path']}").decode(
                    "utf-8-sig", errors="replace"
                ),
            )


def _number(text: str) -> float:
    try:
        return float(text.replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def bulk_net(text: str) -> dict[str, float]:
    """{symbol: one-sided buy value minus one-sided sell value} for one day."""
    sides: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in csv.DictReader(io.StringIO(text)):
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        symbol, client = clean.get("Symbol", ""), clean.get("Client Name", "")
        side = clean.get("Buy / Sell", "").upper()
        if not symbol or side not in ("BUY", "SELL"):
            continue
        value = _number(clean.get("Quantity Traded", "")) * _number(
            clean.get("Trade Price / Wght. Avg. Price", "")
        )
        sides[(symbol, client)][side] += value
    out: dict[str, float] = defaultdict(float)
    for (symbol, _), traded in sides.items():
        if len(traded) == 2:
            continue  # both sides: churn
        out[symbol] += traded.get("BUY", 0.0) - traded.get("SELL", 0.0)
    return dict(out)


def promoter_buys(text: str) -> list[tuple[str, datetime, float]]:
    """(symbol, disclosure time, % acquired) for promoter acquisitions."""
    out = []
    for row in json.loads(text).get("data") or []:
        if row.get("promoterType") != "Y" or row.get("acqSaleType") != "Acquisition":
            continue
        try:
            when = datetime.strptime(str(row.get("timestamp")), "%d-%b-%Y %H:%M").replace(
                tzinfo=IST
            )
        except ValueError:
            continue
        out.append((str(row.get("symbol") or ""), when, _number(str(row.get("totAcqShare") or ""))))
    return out


def ban_list(text: str) -> set[str]:
    out = set()
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2 and parts[1].strip():
            out.add(parts[1].strip())
    return out


def slbm_quantity(text: str) -> dict[str, float]:
    """{symbol: shares lent and borrowed that day}, across all SLBM series."""
    out: dict[str, float] = defaultdict(float)
    for row in csv.reader(io.StringIO(text)):
        if len(row) > 11 and row[1].strip():
            out[row[1].strip()] += _number(row[11])
    return dict(out)


# --- turning reports into trades -------------------------------------------------------


def next_session(sessions: Sequence[date], day: date) -> date | None:
    i = bisect.bisect_right(sessions, day)
    return sessions[i] if i < len(sessions) else None


def session_after(sessions: Sequence[date], when: datetime) -> date | None:
    """The first session whose 09:15 open is after `when`."""
    i = bisect.bisect_left(sessions, when.date())
    if i < len(sessions) and sessions[i] == when.date() and (when.hour, when.minute) < (9, 15):
        return sessions[i]
    j = bisect.bisect_right(sessions, when.date())
    return sessions[j] if j < len(sessions) else None


def trades(snaps: six.Snaps, events: Mapping[str, Mapping[date, float]], direction: int) -> Fills:
    """At most ten a day, highest score first."""
    by_day: dict[date, list[tuple[float, str, five.Fill]]] = defaultdict(list)
    for symbol, days in events.items():
        for d, score in days.items():
            s = snaps.get(symbol, {}).get(d)
            if s is None or s.entry < cs.MIN_PRICE:
                continue
            fill = five.Fill(
                six.DAY_START, direction, s.entry_minute, s.entry, s.exit_minute, s.exit
            )
            by_day[d].append((-score, symbol, fill))
    out: Fills = []
    for d, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        out.extend((d, symbol, fill) for _, symbol, fill in found[: five.MAX_OPEN])
    return out


def bulk_events(
    daily: Sequence[tuple[date, dict[str, float]]], sessions: Sequence[date]
) -> tuple[Events, Events]:
    buys: Events = defaultdict(dict)
    sells: Events = defaultdict(dict)
    for day, net in daily:
        target = next_session(sessions, day)
        if target is None:
            continue
        for symbol, value in net.items():
            if value > 0:
                buys[symbol][target] = value
            elif value < 0:
                sells[symbol][target] = -value
    return buys, sells


def promoter_events(
    found: Sequence[tuple[str, datetime, float]], sessions: Sequence[date]
) -> Events:
    out: Events = defaultdict(dict)
    for symbol, when, share in found:
        target = session_after(sessions, when)
        if target is not None:
            out[symbol][target] = max(out[symbol].get(target, 0.0), share)
    return out


def ban_events(lists: Mapping[date, set[str]]) -> Events:
    out: Events = defaultdict(dict)
    days = sorted(lists)
    for before, today in pairwise(days):
        for symbol in lists[today] - lists[before]:
            out[symbol][today] = 1.0
    return out


def ban_exits(lists: Mapping[date, set[str]]) -> Events:
    """H-0106 (research 166): in the ban list for the previous trade date, not for this one."""
    out: Events = defaultdict(dict)
    days = sorted(lists)
    for before, today in pairwise(days):
        for symbol in lists[before] - lists[today]:
            out[symbol][today] = 1.0
    return out


def slbm_events(
    daily: Sequence[tuple[date, dict[str, float]]], snaps: six.Snaps, sessions: Sequence[date]
) -> Events:
    out: Events = defaultdict(dict)
    for day, quantities in daily:
        target = next_session(sessions, day)
        if target is None:
            continue
        for symbol, quantity in quantities.items():
            days = snaps.get(symbol)
            if not days or day not in days:
                continue
            ordered = [d for d in sorted(days) if d < day][-VALUE_DAYS:]
            if len(ordered) < VALUE_DAYS:
                continue
            mean = sum(days[d].value for d in ordered) / VALUE_DAYS
            ratio = quantity * days[day].last_close / mean if mean > 0 else 0.0
            if ratio >= SLBM_SHARE:
                out[symbol][target] = ratio
    return out


def ban_short_run() -> IntradayRun:
    """H-0096's trades for the validation battery: as screened, and entered 5 minutes late."""
    from eulerlab.validation.intraday import IntradayRun

    snaps, window = fo.load_snaps()
    bans = ban_events(dict(_parsed("fo_ban", ban_list)))
    chosen = trades(snaps, bans, -1)
    on_time = [
        t for d, symbol, fill in chosen if (t := five._trade(symbol, d, fill, -1, five.TRADE))
    ]
    late = []
    for d, symbol, _ in chosen:
        fill = six._from(snaps[symbol][d], 10, -1)  # decide on the 09:25 close, fill after
        if fill is not None and (t := five._trade(symbol, d, fill, -1, five.TRADE)):
            late.append(t)
    return IntradayRun(on_time, late, list(window), five.TRADE * five.MAX_OPEN)


def ban_exit_long_run() -> IntradayRun:
    """H-0106's trades for the validation battery: as screened, and entered 5 minutes late."""
    from eulerlab.validation.intraday import IntradayRun

    snaps, window = fo.load_snaps()
    exits = ban_exits(dict(_parsed("fo_ban", ban_list)))
    chosen = trades(snaps, exits, 1)
    on_time = [
        t for d, symbol, fill in chosen if (t := five._trade(symbol, d, fill, 1, five.TRADE))
    ]
    late = []
    for d, symbol, _ in chosen:
        fill = six._from(snaps[symbol][d], 10, 1)
        if fill is not None and (t := five._trade(symbol, d, fill, 1, five.TRADE)):
            late.append(t)
    return IntradayRun(on_time, late, list(window), five.TRADE * five.MAX_OPEN)


def ban_exit_screen() -> dict[str, Any]:
    """H-0106 screened alone (research 166), measured as research 164's five."""
    snaps, window = fo.load_snaps()
    exits = ban_exits(dict(_parsed("fo_ban", ban_list)))
    return {
        "hypothesis": "H-0106",
        "events": sum(len(v) for v in exits.values()),
        **six.evaluate(
            "nse_fo_ban_exit_long", trades(snaps, exits, 1), window, five.TRADE * five.MAX_OPEN
        ),
    }


DAILY_FIRST = date(2015, 1, 1)
DAILY_OUT = data_path("derived/nse_ban_short_daily.json")
PANEL = data_path("derived/price_panel.jsonl")


def daily_bars(symbols: set[str], path: Path = PANEL) -> dict[str, dict[date, tuple[float, float]]]:
    """{symbol: {day: (official open, official close)}} for the named symbols."""
    out: dict[str, dict[date, tuple[float, float]]] = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["s"] in symbols and row.get("o") and row.get("c"):
                out[row["s"]][date.fromisoformat(row["d"])] = (float(row["o"]), float(row["c"]))
    return out


def daily_ban_trades(
    bans: Mapping[str, Mapping[date, float]], bars: Mapping[str, Mapping[date, tuple[float, float]]]
) -> list[cs.Trade]:
    """H-0098: short at the official open of the first ban day, cover at the close."""
    by_day: dict[date, list[cs.Trade]] = defaultdict(list)
    for symbol, days in bans.items():
        for day in days:
            bar = bars.get(symbol, {}).get(day)
            if bar is None or bar[0] < cs.MIN_PRICE:
                continue
            quantity = cs.sized(five.TRADE, bar[0])
            if quantity:
                trade = cs.Trade(symbol, day, -1, quantity, 0, bar[0], 374, bar[1], "close")
                by_day[day].append(trade)
    out: list[cs.Trade] = []
    for day in sorted(by_day):
        out.extend(sorted(by_day[day], key=lambda t: t.symbol)[: five.MAX_OPEN])
    return out


def run_daily(output: Path = DAILY_OUT) -> dict[str, Any]:
    lists = dict(_parsed("fo_ban", ban_list, DAILY_FIRST))
    bans = ban_events(lists)
    bars = daily_bars(set(bans))
    sessions = sorted(
        {d for days in bars.values() for d in days if DAILY_FIRST <= d <= cs.DATA_END}
    )
    found = daily_ban_trades(bans, bars)
    run = cs.report(
        "nse_fo_ban_entry_short_daily",
        found,
        sessions,
        params={"bars": "NSE official open to close", "slippage_bps_per_side": cs.SLIPPAGE_BPS},
        capital=five.TRADE * five.MAX_OPEN,
    )
    run.pop("daily", None)
    run["trade_log"] = run.get("trade_log", [])[:200]
    result = {
        "hypothesis": "H-0098",
        "research": "docs/RESEARCH/164-bulk-deals-sast-ban-slbm.md",
        "ban_files": len(lists),
        "events": sum(len(v) for v in bans.values()),
        "spent_trials": 0,
        **run,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# --- running ---------------------------------------------------------------------------


def _parsed(
    segment: str, parse: Callable[[str], Any], first: date = FIRST_DAY, through: date | None = None
) -> list[tuple[date, Any]]:
    return sorted((day, parse(text)) for day, text in report_files(segment, first, through))


def run(output: Path = OUT) -> dict[str, Any]:
    snaps, window = fo.load_snaps()
    bulk = _parsed("bulk_deals", bulk_net)
    buys, sells = bulk_events(bulk, window)
    promoters = promoter_events(
        [item for _, found in _parsed("sast", promoter_buys) for item in found], window
    )
    bans = ban_events(dict(_parsed("fo_ban", ban_list)))
    lending = slbm_events(_parsed("slbm", slbm_quantity), snaps, window)
    capital = five.TRADE * five.MAX_OPEN
    rules = (
        ("H-0093", "nse_bulk_deal_buyers", buys, 1),
        ("H-0094", "nse_bulk_deal_sellers", sells, -1),
        ("H-0095", "nse_sast_promoter_buying", promoters, 1),
        ("H-0096", "nse_fo_ban_entry_short", bans, -1),
        ("H-0097", "nse_slbm_heavy_borrowing", lending, -1),
    )
    runs = [
        {
            "hypothesis": hypothesis,
            "events": sum(len(v) for v in events.values()),
            **six.evaluate(run_id, trades(snaps, events, direction), window, capital),
        }
        for hypothesis, run_id, events, direction in rules
    ]
    result = {
        "research": "docs/RESEARCH/164-bulk-deals-sast-ban-slbm.md",
        "report_days": {"bulk_deals": len(bulk)},
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="nse-reports-intraday")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--daily", action="store_true", help="H-0098: daily bars from 2015")
    parser.add_argument("--ban-exit", action="store_true", help="H-0106 alone (research 166)")
    args = parser.parse_args()
    if args.ban_exit:
        one = ban_exit_screen()
        data_path("derived/nse_ban_exit_intraday.json").write_text(json.dumps(one, indent=1))
        print(
            f"H-0106: {one['trades']} trades of {one['events']} events; "
            f"{one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net a trade; net Sharpe {one['net']['sharpe']}; "
            f"by year {[(y, v['total_return']) for y, v in one['net_by_year'].items()]}"
        )
        return 0
    if args.daily:
        daily = run_daily()
        print(
            f"H-0098: {daily['trades']} trades of {daily['events']} events; "
            f"{daily['per_trade_bps']['gross_mean']} bps gross, "
            f"{daily['per_trade_bps']['net_mean']} net a trade; net Sharpe {daily['net']['sharpe']}"
        )
        return 0
    result = run(args.output)
    for one in result["runs"]:
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades of {one['events']} events; "
            f"{one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net a trade; net Sharpe {one['net']['sharpe']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
