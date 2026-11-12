"""`make market-reports` — the Deals & filings tab's summary, from the landed NSE reports.

Reads `data/landing/nse_reports/` (ingest/nse_reports, ADR-095) and writes one
small file, `data/derived/market_reports.json`, that `/api/market-reports`
serves as it is. `make nse-reports` runs this between the download and the
verified upload, so the files it needs are still on disk; a file already
pruned is read back from B2 (about 100 objects, well inside the 2,500 a day).

Each section names the trade date it describes. Nothing here is a signal:
none of these has been through the gate.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from eulerlab.ingest.landing import Landing, ManifestEntry
from eulerlab.ingest.nse_eod import IST
from eulerlab.paths import data_path

LANDING = data_path("landing/nse_reports")
OUT = data_path("derived/market_reports.json")
DEAL_DAYS = 30
FILING_DAYS = 10
MTF_LOOKBACK = 5
TOP = 15
STALE_PLEDGE_DAYS = 200
SHARE_SERIES = frozenset({"EQ", "BE", "SME"})

Reader = Callable[[ManifestEntry], bytes]


def _num(text: object) -> float:
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return 0.0


def _text(payload: bytes) -> str:
    return payload.decode("utf-8-sig", errors="replace")


def _csv(payload: bytes) -> list[dict[str, str]]:
    rows = csv.DictReader(io.StringIO(_text(payload)))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in rows]


# --- parsers, one per report ---------------------------------------------------


def parse_deals(payload: bytes, kind: str) -> list[dict[str, Any]]:
    out = []
    for row in _csv(payload):
        qty, price = (
            _num(row.get("Quantity Traded")),
            _num(row.get("Trade Price / Wght. Avg. Price")),
        )
        if not row.get("Symbol") or not qty:
            continue
        out.append(
            {
                "date": row.get("Date", ""),
                "kind": kind,
                "symbol": row["Symbol"],
                "client": row.get("Client Name", ""),
                "side": row.get("Buy / Sell", "").upper(),
                "qty": int(qty),
                "price": price,
                "value_cr": round(qty * price / 1e7, 2),
            }
        )
    return out


def drop_repeats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """NSE's bulk list repeats a block trade that also passes 0.5% of the company.

    Swiggy, 2026-10-30: Tencent's 5.43 crore-share sale is in both files with
    the same client, side, quantity and price. Counted once, as the block.
    """

    def key(r: dict[str, Any]) -> tuple[Any, ...]:
        return (r["date"], r["symbol"], r["client"], r["side"], r["qty"])

    blocks = {key(r) for r in rows if r["kind"] == "block"}
    return [r for r in rows if r["kind"] == "block" or key(r) not in blocks]


def parse_short_selling(payload: bytes) -> list[dict[str, Any]]:
    return [
        {"symbol": r["Symbol"], "qty": int(_num(r.get("Quantity")))}
        for r in _csv(payload)
        if r.get("Symbol")
    ]


def parse_ban(payload: bytes) -> list[str]:
    lines = [line.strip() for line in _text(payload).splitlines()[1:] if line.strip()]
    return [line.split(",", 1)[1].strip() for line in lines if "," in line]


def parse_mtf(payload: bytes) -> dict[str, Any]:
    """Market totals (₹ lakh) and per-stock funded quantity and amount."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        lines = archive.read(name).decode("utf-8", errors="replace").splitlines()
    totals: dict[str, float] = {}
    stocks: dict[str, dict[str, float]] = {}
    in_table = False
    for row in csv.reader(lines):
        cells = [c.strip() for c in row]
        if len(cells) >= 3 and cells[0] in {"1", "2", "3", "4"}:
            key = {"1": "opening", "2": "fresh", "3": "liquidated", "4": "closing"}[cells[0]]
            totals[key] = _num(cells[2])
        elif cells and cells[0] == "Symbol":
            in_table = True
        elif in_table and len(cells) >= 4 and cells[0]:
            stocks[cells[0]] = {"qty": _num(cells[2]), "lakh": _num(cells[3])}
    return {"totals": totals, "stocks": stocks}


def parse_slbm(payload: bytes) -> dict[str, dict[str, float]]:
    """Per symbol: quantity lent across all series that day, and the best fee.

    # ASSUMPTION: A-077 - in SLBM_BC, field 12 is the quantity traded and
    # field 10 the closing lending fee per share (7 shares x 0.05 = 0.35 in
    # field 13 on the 2026-10-23 file). NSE's layout note was not found.
    """
    out: dict[str, dict[str, float]] = {}
    for row in csv.reader(io.StringIO(_text(payload))):
        if len(row) < 13:
            continue
        symbol = row[1].strip()
        held = out.setdefault(symbol, {"qty": 0.0, "fee": 0.0})
        held["qty"] += _num(row[11])
        held["fee"] = max(held["fee"], _num(row[9]))
    return out


def _s(value: object) -> str:
    """NSE sends null for blank text; the page wants a string."""
    return "" if value is None else str(value).strip()


def _json(payload: bytes) -> Any:
    return json.loads(payload)


def parse_sast(payload: bytes) -> list[dict[str, Any]]:
    out = []
    for r in _json(payload).get("data", []):
        sale = (r.get("acqSaleType") or "").lower().startswith("sale")
        shares = r.get("noOfShareSale") if sale else r.get("noOfShareAcq")
        out.append(
            {
                "time": _s(r.get("timestamp") or r.get("sysTime")),
                "symbol": _s(r.get("symbol")),
                "company": _s(r.get("company")),
                "who": _s(r.get("acquirerName")),
                "promoter": r.get("promoterType") == "Y",
                "side": "SELL" if sale else "BUY",
                "shares": int(_num(shares)),
                "pct": _num(r.get("totSaleShare") if sale else r.get("totAcqShare")),
                "after_pct": _num(r.get("totAftShare")),
                "mode": _s(r.get("acquisitionMode")),
            }
        )
    return out


def parse_insider(payload: bytes) -> list[dict[str, Any]]:
    """NSE's PIT list carries the filing, not the trade: figures are in its XBRL."""
    return [
        {
            "time": _s(r.get("broadcastDateTime")),
            "symbol": _s(r.get("symbol")),
            "company": _s(r.get("companyName")),
            "regulation": _s(r.get("regulation")),
            "type": _s(r.get("typeOfSubmission")),
            "link": _s(r.get("ixbrl")),
        }
        for r in _json(payload).get("data", [])
    ]


def parse_pledges(payload: bytes) -> list[dict[str, Any]]:
    """Companies whose promoters have pledged shares, most of the company first.

    # ASSUMPTION: A-078 - `percPromoterShares` is the pledged share of the
    # promoters' own holding and `percTotShares` the same shares as a share
    # of the company (Afcons: 100.00 and 50.17, promoters holding 50.17%).
    # `percSharesPledged` counts every pledge, not only promoters', so it is
    # not used.
    """
    out = []
    for r in _json(payload).get("data", []):
        of_promoter = _num(r.get("percPromoterShares"))
        if of_promoter <= 0:
            continue
        out.append(
            {
                "company": _s(r.get("comName")),
                "of_promoter_pct": of_promoter,
                "of_company_pct": _num(r.get("percTotShares")),
                "promoter_pct": _num(r.get("percPromoterHolding")),
                "quarter": _s(r.get("shp")),
                "filed": _s(r.get("broadcastDt")),
            }
        )
    return sorted(out, key=lambda r: (-r["of_company_pct"], -r["of_promoter_pct"]))


def parse_ipos(current: bytes | None, past: bytes | None) -> dict[str, Any]:
    open_now = [
        {
            "symbol": _s(r.get("symbol")),
            "company": _s(r.get("companyName")),
            "opens": _s(r.get("issueStartDate")),
            "closes": _s(r.get("issueEndDate")),
            "price": _s(r.get("issuePrice")),
            "subscribed": round(_num(r.get("noOfTime")), 2),
            "series": _s(r.get("series")),
        }
        for r in (_json(current) if current else [])
        if (r.get("category") or "Total") == "Total"
    ]
    listed = []
    for r in _json(past) if past else []:
        when = _date(r.get("listingDate"))
        # Past issues include bonds and units (DEBT, N0, IV...); shares only.
        if when is None or r.get("securityType") not in SHARE_SERIES:
            continue
        listed.append(
            {
                "symbol": _s(r.get("symbol")),
                "company": _s(r.get("company")),
                "listed": when.isoformat(),
                "price": _s(r.get("issuePrice")),
                "series": _s(r.get("securityType")),
            }
        )
    listed.sort(key=lambda r: r["listed"], reverse=True)
    return {"open": open_now, "listed": listed[:TOP]}


def _date(text: object) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(str(text).strip().title(), fmt).replace(tzinfo=IST).date()
        except ValueError:
            continue
    return None


def _stamp(text: object, fmt: str, width: int) -> datetime:
    """NSE's IST filing time; an unreadable one sorts last."""
    try:
        return datetime.strptime(str(text)[:width].replace(",", ""), fmt).replace(tzinfo=IST)
    except ValueError:
        return datetime.min.replace(tzinfo=IST)


# --- the summary ---------------------------------------------------------------


def _by_report(landing: Landing) -> dict[str, list[ManifestEntry]]:
    grouped: dict[str, list[ManifestEntry]] = defaultdict(list)
    for entry in landing.entries().values():
        grouped[entry.segment].append(entry)
    for entries in grouped.values():
        entries.sort(key=lambda e: e.trade_date)
    return grouped


def summarise(landing: Landing, read: Reader) -> dict[str, Any]:
    """Every section from the latest landed days. A missing report says so."""
    reports = _by_report(landing)

    def last(name: str, n: int = 1) -> list[ManifestEntry]:
        return [e for e in reports.get(name, []) if e.rows > 0][-n:]

    def section(build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return {"available": True, **build()}
        except Exception as exc:  # one bad report must not blank the others
            return {"available": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}

    def deals() -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        days = {e.trade_date for e in last("bulk_deals", DEAL_DAYS)}
        for kind in ("bulk", "block"):
            for entry in reports.get(f"{kind}_deals", []):
                if entry.trade_date in days and entry.rows:
                    rows.extend(parse_deals(read(entry), kind))
        if not rows:
            raise ValueError("no deals landed in the window")
        rows = drop_repeats(rows)
        latest = max(days)
        today = [r for r in rows if _date(r["date"]) == date.fromisoformat(latest)]
        net: dict[str, dict[str, float]] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
        for r in rows:
            net[r["client"]]["buy" if r["side"] == "BUY" else "sell"] += r["value_cr"]
        clients: list[dict[str, Any]] = [
            {
                "client": c,
                "buy_cr": round(v["buy"], 1),
                "sell_cr": round(v["sell"], 1),
                "net_cr": round(v["buy"] - v["sell"], 1),
            }
            for c, v in net.items()
        ]
        return {
            "as_of": latest,
            "since": min(days),
            "today": sorted(today, key=lambda r: -r["value_cr"])[:25],
            "today_count": len(today),
            "largest": sorted(rows, key=lambda r: -r["value_cr"])[:TOP],
            "buyers": sorted(clients, key=lambda r: -r["net_cr"])[:10],
            "sellers": sorted(clients, key=lambda r: r["net_cr"])[:10],
            "count": len(rows),
        }

    def ban() -> dict[str, Any]:
        two = list(reports.get("fo_ban", []))[-2:]
        now = parse_ban(read(two[-1]))
        before = parse_ban(read(two[0])) if len(two) == 2 else []
        return {
            "as_of": two[-1].trade_date,
            "symbols": now,
            "added": [s for s in now if s not in before],
            "removed": [s for s in before if s not in now],
        }

    def mtf() -> dict[str, Any]:
        entries = last("mtf", MTF_LOOKBACK + 1)
        now = parse_mtf(read(entries[-1]))
        then = parse_mtf(read(entries[0])) if len(entries) > 1 else {"stocks": {}}
        rows = []
        for symbol, cur in now["stocks"].items():
            old = then["stocks"].get(symbol, {}).get("lakh", 0.0)
            change = (cur["lakh"] - old) / old if old > 0 else None
            rows.append(
                {
                    "symbol": symbol,
                    "cr": round(cur["lakh"] / 100, 1),
                    "change": None if change is None else round(change, 4),
                }
            )
        movers = [r for r in rows if r["change"] is not None and r["cr"] >= 50]
        return {
            "as_of": entries[-1].trade_date,
            "compared_with": entries[0].trade_date,
            "totals_cr": {k: round(v / 100, 0) for k, v in now["totals"].items()},
            "largest": sorted(rows, key=lambda r: -r["cr"])[:TOP],
            "rising": sorted(movers, key=lambda r: -(r["change"] or 0))[:10],
            "falling": sorted(movers, key=lambda r: r["change"] or 0)[:10],
        }

    def shorts() -> dict[str, Any]:
        entry = last("short_selling")[-1]
        rows = sorted(parse_short_selling(read(entry)), key=lambda r: -r["qty"])
        lent: list[dict[str, Any]] = []
        slb = last("slbm")
        if slb:
            lent = [
                {"symbol": s, "qty": int(v["qty"]), "fee": v["fee"]}
                for s, v in parse_slbm(read(slb[-1])).items()
                if v["qty"] > 0
            ]
            lent.sort(key=lambda r: -r["qty"])
        return {
            "as_of": entry.trade_date,
            "short_sold": rows[:TOP],
            "short_count": len(rows),
            "slbm_as_of": slb[-1].trade_date if slb else None,
            "lent": lent[:TOP],
        }

    def filings() -> dict[str, Any]:
        sast = [r for e in last("sast", FILING_DAYS) for r in parse_sast(read(e))]
        pit = [r for e in last("insider", FILING_DAYS) for r in parse_insider(read(e))]
        sast.sort(key=lambda r: _stamp(r["time"], "%d-%b-%Y %H:%M", 17), reverse=True)
        pit.sort(key=lambda r: _stamp(r["time"], "%d-%b-%Y %H:%M:%S", 20), reverse=True)
        return {
            "days": FILING_DAYS,
            "sast": sast[:25],
            "insider": pit[:25],
            "insider_count": len(pit),
        }

    def pledges() -> dict[str, Any]:
        entry = last("pledges")[-1]
        # A company that stopped filing keeps its last quarter in NSE's list
        # (DQ Entertainment: September 2023); only the last two quarters count.
        cutoff = date.fromisoformat(entry.trade_date).toordinal() - STALE_PLEDGE_DAYS
        rows = [
            r
            for r in parse_pledges(read(entry))
            if (q := _date(r["quarter"])) is not None and q.toordinal() >= cutoff
        ]
        return {"as_of": entry.trade_date, "top": rows[:TOP], "count": len(rows)}

    def ipos() -> dict[str, Any]:
        cur, past = last("ipo_current"), last("ipo_past")
        if not past:
            raise ValueError("no IPO list landed yet")
        return {
            "as_of": past[-1].trade_date,
            **parse_ipos(read(cur[-1]) if cur else None, read(past[-1])),
        }

    return {
        "ok": True,
        "built_at": datetime.now(UTC).isoformat(),
        "deals": section(deals),
        "ban": section(ban),
        "mtf": section(mtf),
        "shorts": section(shorts),
        "filings": section(filings),
        "pledges": section(pledges),
        "ipos": section(ipos),
    }


def reader(landing_root: Path) -> Reader:
    """Local bytes when on disk, else the B2 copy `upload-verified` left."""
    store: Any = None
    prefix = ""

    def read(entry: ManifestEntry) -> bytes:
        nonlocal store, prefix
        path = landing_root / entry.path
        if path.exists():
            return path.read_bytes()
        if store is None:
            from eulerlab.env import load_env
            from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config

            load_env()
            config = load_storage_config(Path("config/storage.yaml"))
            store, prefix = S3ObjectStore(config), config.prefix
        return bytes(store.get(f"{prefix}{landing_root.name}/{entry.path}"))

    return read


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-reports")
    parser.add_argument("--landing", type=Path, default=LANDING)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    summary = summarise(Landing(args.landing), reader(args.landing))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".part")
    tmp.write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(args.out)
    missing = [k for k, v in summary.items() if isinstance(v, dict) and not v.get("available")]
    print(
        f"market-reports: wrote {args.out}" + (f"; missing {', '.join(missing)}" if missing else "")
    )
    for name in missing:
        print(f"  {name}: {summary[name]['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
