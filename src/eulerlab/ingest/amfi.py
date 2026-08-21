"""Mutual fund NAVs from AMFI, and full history from mfapi.in.

Two sources with different jobs:

**AMFI's `NAVAll.txt`** is the industry body's own daily publication — every
scheme, its ISINs, and one NAV. It is the authority, and it is a *snapshot*: it
says what today is, never what yesterday was. So it is landed once per day,
immutably, and running the ingest daily is what accumulates history going
forward.

**mfapi.in** serves the past per scheme, which is what fills in everything
before we started looking. It is a community mirror of AMFI data rather than a
primary source, and that is recorded rather than glossed: where the two
disagree, AMFI wins.

### The URL moved and the old one fails quietly

`https://www.amfiindia.com/spages/NAVAll.txt` now returns a 302 to
`portal.amfiindia.com`. Fetched without following redirects it yields a short
HTML "Document Moved" page — which parses as *zero schemes* rather than as an
error. A scraper written against the old URL keeps running and quietly ingests
nothing, which is how a data pipeline dies without anyone noticing. So the
parser **refuses a file with no schemes in it** instead of returning an empty
list.

### knowledge_time is the day after the NAV date

AMFI publishes a scheme's NAV for day D on the evening of D, by 11pm IST. A
strategy deciding at the close on D therefore cannot have seen it. Setting
`knowledge_time = D` would hand the backtest a number published hours after its
own decision — the same lookahead the whole firewall exists to prevent, and
`docs/HISTORY.md` correction 1 is what it costs to get wrong. So
`knowledge_time = D + 1 day`, which is conservative by up to one day and never
optimistic.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

NAV_ALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
MFAPI_URL = "https://api.mfapi.in/mf"

LANDING = Path("data/landing/mf")
SNAPSHOT_DIR = LANDING / "navall"
HISTORY_DIR = LANDING / "history"

USER_AGENT = "EulerLab/0.1 (research; contact via repository)"
"""Identifies the client honestly rather than impersonating a browser.

`~/Documents/Trade` sends a full Chrome user-agent string. That is a small lie
told to a server, and it also makes our traffic indistinguishable from a
person's when someone is trying to work out what is hitting them.
"""


@dataclass(frozen=True)
class Scheme:
    """One scheme as AMFI publishes it."""

    scheme_code: str
    isin_growth: str
    isin_reinvest: str
    name: str
    plan: str
    option: str
    nav: float
    nav_date: date
    amc: str

    @property
    def knowledge_time(self) -> date:
        """When we could first have known this NAV. See the module docstring."""
        return self.nav_date + timedelta(days=1)

    @property
    def is_direct_growth(self) -> bool:
        """Direct plan, growth option — the variant worth analysing.

        Regular plans carry distributor commission, and payout options move
        cash out of the NAV, so neither is comparable across funds. Both are
        still landed; this only marks which subset a study should default to.
        """
        return "direct" in self.plan.lower() and "growth" in self.option.lower()


def _fetch(url: str, *, timeout: int = 60, retries: int = 3) -> bytes:
    """GET with backoff. Redirects are followed, which is the whole point."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body: bytes = response.read()
                return body
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(2**attempt)
    msg = f"{url} failed after {retries} attempts: {last}"
    raise RuntimeError(msg)


def parse_navall(text: str) -> list[Scheme]:
    """Parse AMFI's pipe-delimited dump.

    Raises on a file with no schemes rather than returning `[]`. An empty list
    is indistinguishable from "the market published nothing today", and the
    realistic cause is a moved URL or an error page — a silent zero is how this
    pipeline would rot without anyone noticing.
    """
    schemes: list[Scheme] = []
    amc = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            # AMC names appear as bare lines between blocks of their schemes.
            if not line.lower().startswith("scheme code"):
                amc = line
            continue

        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 8 or not parts[0].isdigit():
            continue
        try:
            nav = float(parts[6])
            nav_date = datetime.strptime(parts[7], "%d-%b-%Y").replace(tzinfo=UTC).date()
        except (ValueError, IndexError):
            # A suspended scheme publishes "N.A." rather than a number. Skipping
            # is right; guessing a value would invent a price.
            continue

        schemes.append(
            Scheme(
                scheme_code=parts[0],
                isin_growth=parts[1] if parts[1] != "-" else "",
                isin_reinvest=parts[2] if parts[2] != "-" else "",
                name=parts[3],
                plan=parts[4],
                option=parts[5],
                nav=nav,
                nav_date=nav_date,
                amc=amc,
            )
        )

    if not schemes:
        msg = (
            "AMFI returned no schemes. The usual cause is the URL having moved — "
            "www.amfiindia.com now 302s to portal.amfiindia.com, and the redirect "
            "page parses as zero rows. Refusing rather than landing an empty day."
        )
        raise ValueError(msg)
    return schemes


def fetch_universe() -> list[Scheme]:
    """Today's NAV for every scheme AMFI publishes."""
    return parse_navall(_fetch(NAV_ALL_URL).decode("utf-8", errors="replace"))


def land_snapshot(*, directory: Path = SNAPSHOT_DIR) -> tuple[Path, int]:
    """Write today's AMFI file to the landing zone, gzipped and immutable.

    Named for the NAV date it contains, not for the day it was fetched: two
    fetches on the same day hold the same NAVs, and a file named by fetch time
    would land the same data twice under different names.

    Idempotent — an existing snapshot is never rewritten, because the landing
    zone is immutable and a re-fetch that overwrote it could silently change
    history.
    """
    schemes = fetch_universe()
    nav_date = max(s.nav_date for s in schemes)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{nav_date.isoformat()}.jsonl.gz"

    if path.exists():
        return path, 0

    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for s in schemes:
            handle.write(
                json.dumps(
                    {
                        "scheme_code": s.scheme_code,
                        "isin_growth": s.isin_growth,
                        "isin_reinvest": s.isin_reinvest,
                        "name": s.name,
                        "amc": s.amc,
                        "plan": s.plan,
                        "option": s.option,
                        "nav": s.nav,
                        "event_time": s.nav_date.isoformat(),
                        "knowledge_time": s.knowledge_time.isoformat(),
                        "receipt_time": datetime.now(UTC).isoformat(),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return path, len(schemes)


def history_path(scheme_code: str, *, directory: Path = HISTORY_DIR) -> Path:
    return directory / f"{scheme_code}.jsonl.gz"


def landed_through(scheme_code: str, *, directory: Path = HISTORY_DIR) -> date | None:
    """The newest NAV date already on disk for a scheme, or None.

    This is what makes the backfill resumable: a scheme already current is
    skipped without a request, so re-running costs nothing and a interrupted
    run picks up where it stopped.
    """
    path = history_path(scheme_code, directory=directory)
    if not path.exists():
        return None
    newest: date | None = None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            when = date.fromisoformat(json.loads(line)["event_time"])
            if newest is None or when > newest:
                newest = when
    return newest


def fetch_history(scheme_code: str) -> list[dict[str, object]]:
    """Full NAV history for one scheme from mfapi.in, oldest first."""
    body = _fetch(f"{MFAPI_URL}/{scheme_code}")
    payload = json.loads(body)
    rows: list[dict[str, object]] = []

    for point in payload.get("data", []):
        try:
            when = datetime.strptime(str(point["date"]), "%d-%m-%Y").replace(tzinfo=UTC).date()
            nav = float(point["nav"])
        except (ValueError, KeyError, TypeError):
            continue
        rows.append(
            {
                "scheme_code": scheme_code,
                "nav": nav,
                "event_time": when.isoformat(),
                "knowledge_time": (when + timedelta(days=1)).isoformat(),
                "source": "mfapi.in",
            }
        )

    rows.sort(key=lambda r: str(r["event_time"]))
    return rows


def land_history(scheme_code: str, *, directory: Path = HISTORY_DIR) -> int:
    """Land one scheme's history. Returns rows written; 0 means already current."""
    rows = fetch_history(scheme_code)
    if not rows:
        return 0

    directory.mkdir(parents=True, exist_ok=True)
    path = history_path(scheme_code, directory=directory)
    receipt = datetime.now(UTC).isoformat()

    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({**row, "receipt_time": receipt}, sort_keys=True) + "\n")
    return len(rows)
