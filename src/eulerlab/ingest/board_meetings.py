"""NSE board-meeting intimations, captured daily into a results calendar (ADR-105).

NSE's RSS feed `Board_Meetings.xml` lists only the day's new intimations: 124
on 2026-10-31, 70 of them meetings to approve financial results, each with its
meeting date. There is no free archive, so the calendar is built forward: each
day's feed is landed unedited under `data/landing/nse_board_meetings/` and
every intimation not seen before is appended to
`data/derived/board_meetings.jsonl` with the meeting date as `event_time` and
the landing time as `knowledge_time`. Companies are named, not symbolled, so
the symbol is looked up from `data/derived/nse_names.json` by name.

The market brief reads `upcoming` for "results due". Until the calendar has a
week or two of history, it misses meetings announced before capture began,
and says so.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.paths import data_path

URL = "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml"
LANDING = data_path("landing/nse_board_meetings")
OUT = data_path("derived/board_meetings.jsonl")
NAMES = data_path("derived/nse_names.json")
SEGMENT = "board_meetings"
IST = ZoneInfo("Asia/Kolkata")
MEETING = re.compile(r"Meeting Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})")
RESULTS = re.compile(r"financial result", re.IGNORECASE)
SUFFIX = re.compile(r"\b(limited|ltd\.?|the)\b", re.IGNORECASE)


def _key(name: str) -> str:
    return " ".join(SUFFIX.sub(" ", name.lower()).replace(".", " ").replace(",", " ").split())


def symbols_by_name(path: Path | None = None) -> dict[str, str]:
    path = path or NAMES
    try:
        names = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {_key(str(n)): str(s) for s, n in names.items()} if isinstance(names, dict) else {}


def parse(payload: bytes, lookup: Mapping[str, str]) -> list[dict[str, Any]] | None:
    """The intimations in one feed, or None when it is not the feed we expect."""
    if b"<!doctype" in payload[:2048].lower() or b"<!entity" in payload.lower():
        return None
    try:
        root = ET.fromstring(payload.strip())
    except ET.ParseError:
        return None
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        return None
    out = []
    for node in channel.findall("item"):
        company = (node.findtext("title") or "").strip()
        text = " ".join((node.findtext("description") or "").split())
        when = MEETING.search(text)
        if not company or not when:
            continue
        try:
            meeting = datetime.strptime(when.group(1), "%d-%b-%Y").replace(tzinfo=IST).date()
        except ValueError:
            continue
        link = (node.findtext("link") or "").strip()
        out.append(
            {
                "company": company[:200],
                "symbol": lookup.get(_key(company), ""),
                "meeting": meeting.isoformat(),
                "results": bool(RESULTS.search(text)),
                "purpose": text[:400],
                "link": link[:500],
                "key": hashlib.sha256(f"{company}|{meeting}|{link}".encode()).hexdigest()[:16],
            }
        )
    return out


def held(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or OUT
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def record(rows: Sequence[dict[str, Any]], knowledge_time: str, path: Path | None = None) -> int:
    path = path or OUT
    seen = {str(r.get("key")) for r in held(path)}
    fresh = [r for r in rows if r["key"] not in seen]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(
                json.dumps(
                    {**row, "event_time": row["meeting"], "knowledge_time": knowledge_time},
                    sort_keys=True,
                )
                + "\n"
            )
    return len(fresh)


def upcoming(
    today: date,
    *,
    days: int = 7,
    rows: Sequence[Mapping[str, Any]] | None = None,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    """Results meetings from `today` to `today + days`, known by `as_of` (ISO), soonest first."""
    end = (today + timedelta(days=days)).isoformat()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows if rows is not None else held():
        if not row.get("results") or not today.isoformat() <= str(row.get("meeting")) <= end:
            continue
        if as_of is not None and str(row.get("knowledge_time", "")) > as_of:
            continue
        out[(str(row["company"]), str(row["meeting"]))] = dict(row)
    return sorted(out.values(), key=lambda r: (r["meeting"], r["company"]))


def capture(today: date | None = None) -> str:
    from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
    from eulerlab.ingest.landing import Landing

    now = datetime.now(IST)
    today = today or now.date()
    landing = Landing(LANDING)
    entry = landing.entries().get((today.isoformat(), SEGMENT))
    if entry is not None and (landing.root / entry.path).exists():
        return "skipped (already landed today)"
    got = Fetcher(UrllibTransport(), FetchPolicy(max_attempts=2)).get(URL)
    if got.outcome is not Outcome.OK or got.payload is None:
        return f"failed ({got.detail or got.status})"
    rows = parse(got.payload, symbols_by_name())
    if rows is None:
        return "malformed (not the board meetings feed)"
    landed = landing.write(
        trade_date=today,
        segment=SEGMENT,
        file_format="rss",
        url=URL,
        payload=got.payload,
        rows=len(rows),
        inner_name=f"board_meetings_{today.isoformat()}.xml",
        suffix="xml",
    )
    added = record(rows, landed.knowledge_time)
    return f"downloaded: {len(rows)} intimation(s), {added} new, {sum(r['results'] for r in rows)} for results"


def main() -> int:
    outcome = capture()
    print(f"board meetings: {outcome}")
    return 1 if outcome.startswith(("failed", "malformed")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
