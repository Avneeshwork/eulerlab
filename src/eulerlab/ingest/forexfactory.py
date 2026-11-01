"""The ForexFactory economic calendar, snapshotted weekly.

### What this feed is, and what it is not

`https://nfs.faireconomy.media/ff_calendar_thisweek.json` returns roughly a
hundred events for the current week: title, country, timestamp, impact rating,
forecast and previous.

Three limits, all measured on 2026-08-23 rather than assumed:

- **One week only.** `lastweek`, `nextweek`, `thismonth` and `lastmonth` all
  return 404. There is no history endpoint.
- **No `actual`.** Neither the JSON nor the XML carries the released value —
  only forecast and previous. So *surprise*, which is what actually moves a
  price on a release, cannot be computed from this feed at all.
- **Rate limited** to two downloads per five minutes, per ForexFactory's own
  notice.

That makes it a **forward calendar**, not a research dataset. It can say what is
coming and gate a strategy on event days; it cannot backfill Mesfin's 993-event
study, and nothing here should be described as though it could.

### Which is why this is append-only

History has to be *accumulated*. Each run appends the current week, keyed so a
re-run supersedes rather than duplicates, and after a year of daily runs there
is a year of calendar — going forward only. That is the same shape the AMFI
snapshot uses for the same reason: the source publishes a present, not a past.

Every record carries `event_time` (when the release happens),
`knowledge_time` (when it could first have been known — for a forward calendar
that is the fetch, since the schedule is published ahead) and `receipt_time`.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

LANDING = Path("data/landing/calendar")
FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

IMPACTS = ("High", "Medium", "Low", "Holiday")
"""ForexFactory's own ratings, in descending order of consequence."""


@dataclass(frozen=True)
class Event:
    """One scheduled release."""

    title: str
    country: str
    """A currency code (`USD`, `INR`, `EUR`), not an ISO country. That is the
    feed's convention and it is kept rather than translated: `EUR` covers
    nineteen countries and any mapping to one of them would be invented."""

    event_time: str
    impact: str
    forecast: str
    previous: str
    knowledge_time: str
    receipt_time: str

    @property
    def key(self) -> str:
        """What makes two records the same event.

        Title plus timestamp plus currency. A re-run of the same week must
        supersede rather than append, or a daily job would multiply every event
        by seven inside a week.
        """
        return f"{self.event_time}|{self.country}|{self.title}"

    def to_row(self) -> dict[str, object]:
        return {
            "title": self.title,
            "country": self.country,
            "event_time": self.event_time,
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
            "knowledge_time": self.knowledge_time,
            "receipt_time": self.receipt_time,
            "key": self.key,
        }


def fetch(*, timeout: int = 45, retries: int = 3) -> list[dict[str, object]]:
    """The current week's events, raw.

    Backs off generously: the published limit is two downloads per five
    minutes, so a tight retry loop would earn a block rather than a file.
    """
    request = urllib.request.Request(FEED, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload if isinstance(payload, list) else []
        except (urllib.error.URLError, TimeoutError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(20 * (attempt + 1))
    return []


def to_events(raw: list[dict[str, object]], *, now: datetime | None = None) -> list[Event]:
    """Raw feed rows into records that carry their own provenance."""
    stamp = (now or datetime.now(UTC)).isoformat()
    out: list[Event] = []
    for row in raw:
        title = str(row.get("title") or "").strip()
        when = str(row.get("date") or "").strip()
        if not title or not when:
            continue
        try:
            moment = datetime.fromisoformat(when)
        except ValueError:
            continue
        out.append(
            Event(
                title=title,
                country=str(row.get("country") or "").strip(),
                event_time=moment.astimezone(UTC).isoformat(),
                impact=str(row.get("impact") or "").strip(),
                forecast=str(row.get("forecast") or "").strip(),
                previous=str(row.get("previous") or "").strip(),
                # The schedule is published ahead, so it is knowable from the
                # moment it is fetched. That is not true of the released value,
                # which this feed never carries.
                knowledge_time=stamp,
                receipt_time=stamp,
            )
        )
    return out


def week_path(day: date, *, root: Path = LANDING) -> Path:
    """One file per ISO week, so a re-run lands on the same place."""
    iso = day.isocalendar()
    return root / f"{iso.year}-W{iso.week:02d}.jsonl.gz"


def land(*, root: Path = LANDING, now: datetime | None = None) -> tuple[int, int]:
    """Fetch the week and merge it into its file. Returns (events, new).

    Merged rather than overwritten: a week fetched on Monday and again on
    Friday should end with one row per event, and the later fetch is the more
    complete one because forecasts firm up as a release approaches.
    """
    events = to_events(fetch(), now=now)
    if not events:
        return 0, 0

    when = datetime.fromisoformat(events[0].event_time).date()
    path = week_path(when, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict[str, object]] = {}
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                existing[str(row.get("key", ""))] = row

    before = len(existing)
    for event in events:
        existing[event.key] = event.to_row()

    tmp = path.with_suffix(".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in sorted(existing.values(), key=lambda r: str(r.get("event_time", ""))):
            handle.write(json.dumps(row) + "\n")
    tmp.replace(path)
    return len(existing), len(existing) - before


def read_all(
    *, root: Path = LANDING, allow_cloud: bool = True, stale_ok: bool = False
) -> list[Event]:
    """Every landed event, from disk or the bucket.

    `stale_ok` is for the dashboard: the bucket listing comes from the saved
    copy and is refreshed in the background (`landing_reader.available`), so
    the first snapshot after a restart does not wait 1.3 s on the bucket.
    """
    from eulerlab.ingest import landing_reader

    out: list[Event] = []
    if allow_cloud:
        paths = landing_reader.available("calendar", "*.jsonl.gz", stale_ok=stale_ok)
        loader = landing_reader.read
    else:
        paths = [str(p.relative_to(Path("data/landing"))) for p in sorted(root.glob("*.jsonl.gz"))]

        def loader(relative: str, **_: object) -> bytes:
            return (Path("data/landing") / relative).read_bytes()

    for relative in paths:
        try:
            text = gzip.decompress(loader(relative)).decode("utf-8")
        except (OSError, ValueError, EOFError, FileNotFoundError):
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                out.append(
                    Event(
                        title=str(row["title"]),
                        country=str(row.get("country", "")),
                        event_time=str(row["event_time"]),
                        impact=str(row.get("impact", "")),
                        forecast=str(row.get("forecast", "")),
                        previous=str(row.get("previous", "")),
                        knowledge_time=str(row.get("knowledge_time", "")),
                        receipt_time=str(row.get("receipt_time", "")),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
    out.sort(key=lambda e: e.event_time)
    return out


def latest_schedule(events: list[Event]) -> list[Event]:
    """One row per release: when the source moves an event's time, the newer
    record wins.

    The landing key includes the time, so a release moved from 08:00 to 08:32
    lands as a second record and both used to show (BOJ Policy Rate, 2026-W43,
    T-4345). Grouped by country, title and calendar day; the record with the
    latest `knowledge_time` is the schedule as last published. The landed
    files are not changed.
    """
    best: dict[tuple[str, str, str], Event] = {}
    for event in events:
        group = (event.country, event.title, event.event_time[:10])
        held = best.get(group)
        if held is None or event.knowledge_time > held.knowledge_time:
            best[group] = event
    return sorted(best.values(), key=lambda e: e.event_time)


def main() -> int:
    total, new = land()
    print(f"calendar: {total} events in the week, {new} new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
