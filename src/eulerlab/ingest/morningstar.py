"""Morningstar India fund ratings — the one thing AMFI does not publish.

ADR-038 chose AMFI over Morningstar for NAVs and said the star and analyst
ratings were the only thing Morningstar had that AMFI lacked. This fetches
exactly that and nothing else.

### Why the previous attempt got six rows

`~/Documents/Trade`'s scraper read the first page and stopped. The page holds
**5,741 funds** across 230 pages of 25. It is ASP.NET: paging happens through
`__doPostBack` with `__VIEWSTATE` and `__EVENTVALIDATION` carried between
requests, so a plain GET loop cannot walk it. Setting the page size to 200
brings it down to ~29 requests, which is the difference between polite and
rude.

### The ratings are not text

`Medalist Rating` and `Star Rating` render as icons. The values live in a CSS
class (`analyst-rating-icon-bronze`) and a `title` attribute
(`title='Star Rating 3'`). Extracting the cell's text returns an empty string,
which is what made the old scraper's few rows useless even where it had them.

### There is no ISIN, and that matters

The page carries a Morningstar fund id (`f00000pdux`) and a fund name. **It
carries no ISIN and no AMFI scheme code.** `CLAUDE.md` is unambiguous —
*instrument joins use internal IDs only, never a ticker* — so joining these
ratings to AMFI schemes on the fund name would break the project's central
identity rule.

The resolution is to not pretend. Ratings are landed keyed by Morningstar's own
id, complete and independent. A name-based join is offered separately, reports
its match rate, and is labelled `fuzzy` on every row it produces. A rating
attached to the wrong scheme is worse than a rating attached to nothing.
"""

from __future__ import annotations

import gzip
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http.cookiejar import CookieJar
from pathlib import Path

URL = "https://www.morningstar.in/featured-reports.aspx"
LANDING = Path("data/landing/mf/morningstar")

USER_AGENT = "EulerLab/0.1 (research; contact via repository)"

NEXT_LABEL = "Next >"
"""The pager control is found by its label, never by a fixed id.

Hardcoding one cost a run: `...pagerQualitativeRatings$ctl02$ctl01` is the
literal "2" link, not "next". Clicking it repeatedly re-served page 2 forever,
and the crawl stopped at 400 of 5,741 rows. The ids also shift when the page
size changes, so any fixed id is wrong twice over.
"""
ROWS_TARGET = "ctl00$ContentPlaceHolder1$ddlShowRowCount"


@dataclass(frozen=True)
class Rating:
    """One fund's Morningstar assessment.

    `morningstar_id` is the only identifier the page provides that is stable.
    The name is what a human reads and what a join would have to use, which is
    why the join is kept separate from the record.
    """

    morningstar_id: str
    name: str
    category: str
    medalist: str
    """Gold / Silver / Bronze / Neutral / Negative, or empty when unrated."""

    star_rating: int | None
    """1-5, or None.

    None means unrated. The page renders that as "Star Rating 0"; it is stored
    as None because 0 is not a point on Morningstar's scale, and a fund nobody
    rated is not a fund rated worst.
    """

    equity_stylebox: int | None
    fixed_income_stylebox: int | None
    rating_date: date | None


def _token(page: str, field: str) -> str:
    match = re.search(rf'id="{field}"[^>]*value="([^"]*)"', page)
    return html.unescape(match.group(1)) if match else ""


def _form_state(page: str) -> dict[str, str]:
    """The ASP.NET tokens that must ride along on every POST."""
    return {
        "__VIEWSTATE": _token(page, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _token(page, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _token(page, "__EVENTVALIDATION"),
    }


def next_target(page: str) -> str:
    """The postback target behind the "Next >" link, or "" on the last page.

    Read from the page each time. An empty string is a real end condition and
    the caller stops on it rather than clicking something else.
    """
    for match in re.finditer(r"__doPostBack\(&#39;([^&]+)&#39;[^>]*>\s*([^<]{1,14})\s*</a>", page):
        if html.unescape(match.group(2)).strip() == NEXT_LABEL:
            return html.unescape(match.group(1))
    return ""


def _stylebox(cell: str) -> int | None:
    match = re.search(r"stylesmall_new(\d+)\.gif", cell)
    return int(match.group(1)) if match else None


def parse_page(page: str) -> list[Rating]:
    """Every fund row on one page.

    Returns `[]` for a page with no rows rather than raising — unlike the AMFI
    parser, an empty page here is a real end-of-pagination condition and the
    caller checks the running total against the site's own count.
    """
    out: list[Rating] = []
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", page)

    for row in re.findall(r'(?is)<tr class="mds-data-table__row".*?</tr>', body):
        link = re.search(r"/mutualfunds/(f[0-9a-z]+)/[^']*'\s*title='([^']*)'", row)
        if not link:
            continue

        cells = re.findall(r"(?is)<td.*?</td>", row)
        text = [html.unescape(re.sub(r"(?is)<[^>]+>", " ", c)) for c in cells]

        medalist = ""
        icon = re.search(r"analyst-rating-icon-([a-z]+)'\s*title='([^']*)'", row)
        if icon:
            medalist = icon.group(2).strip()

        stars: int | None = None
        star = re.search(r"Star Rating (\d)", row)
        if star:
            # Morningstar's scale is 1-5. The page renders an unrated fund as
            # "Star Rating 0", and storing that as 0 would make "nobody rated
            # this" indistinguishable from "rated worst" — the same null-versus-
            # zero confusion that made a 0-fill backtest read as no-edge.
            value = int(star.group(1))
            stars = value if value > 0 else None

        rating_date: date | None = None
        when = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", text[-1] if text else "")
        if when:
            rating_date = datetime.strptime(when.group(1), "%b %d, %Y").replace(tzinfo=UTC).date()

        category = ""
        if len(text) > 1:
            category = re.sub(r"\s+", " ", text[1].replace("Category :", "")).strip()

        out.append(
            Rating(
                morningstar_id=link.group(1),
                name=html.unescape(link.group(2)).strip(),
                category=category,
                medalist=medalist,
                star_rating=stars,
                equity_stylebox=_stylebox(cells[3]) if len(cells) > 3 else None,
                fixed_income_stylebox=_stylebox(cells[4]) if len(cells) > 4 else None,
                rating_date=rating_date,
            )
        )
    return out


def total_rows(page: str) -> int:
    match = re.search(r'lblTotalRows"[^>]*>(\d+)<', page)
    return int(match.group(1)) if match else 0


class _Session:
    """A cookie-carrying opener. ASP.NET paging does not work without it."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def open(self, data: dict[str, str] | None = None, *, timeout: int = 60) -> str:
        payload = urllib.parse.urlencode(data).encode() if data else None
        request = urllib.request.Request(
            URL,
            data=payload,
            headers={
                "User-Agent": USER_AGENT,
                **({"Content-Type": "application/x-www-form-urlencoded"} if payload else {}),
            },
        )
        for attempt in range(3):
            try:
                with self._opener.open(request, timeout=timeout) as response:
                    body: bytes = response.read()
                    return body.decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        return ""


def fetch_all(*, page_size: int = 200, pace: float = 1.5, max_pages: int = 40) -> list[Rating]:
    """Walk every page, carrying ViewState forward.

    `pace` defaults to 1.5s because this is a real site being walked ~29 times,
    and `max_pages` is a hard stop so a pagination bug cannot turn into an
    unbounded loop against someone else's server.
    """
    session = _Session()
    page = session.open()
    expected = total_rows(page)

    # Raise the page size first: 5,741 rows at 25 a page is 230 requests, at
    # 200 it is 29.
    state = _form_state(page)
    page = session.open(
        {
            **state,
            "__EVENTTARGET": ROWS_TARGET,
            "__EVENTARGUMENT": "",
            ROWS_TARGET: str(page_size),
        }
    )

    seen: dict[str, Rating] = {}
    for number in range(1, max_pages + 1):
        rows = parse_page(page)
        if not rows:
            break
        before = len(seen)
        for rating in rows:
            seen[rating.morningstar_id] = rating
        print(f"  page {number:>3}: {len(rows):>3} rows, {len(seen):>5} unique")

        # A page that adds nothing new means paging stopped advancing — the
        # ViewState went stale, or the pager reached the end without saying so.
        if len(seen) == before or len(seen) >= expected > 0:
            break

        target = next_target(page)
        if not target:
            break

        time.sleep(pace)
        state = _form_state(page)
        page = session.open(
            {
                **state,
                "__EVENTTARGET": target,
                "__EVENTARGUMENT": "",
                ROWS_TARGET: str(page_size),
            }
        )

    print(f"  site reports {expected:,} rows; collected {len(seen):,}")
    return sorted(seen.values(), key=lambda r: r.morningstar_id)


def land(ratings: list[Rating], *, directory: Path = LANDING) -> Path:
    """Write one immutable dated snapshot.

    Named by the newest rating date it contains rather than by fetch time, so
    re-fetching the same publication does not land it twice.
    """
    directory.mkdir(parents=True, exist_ok=True)
    dates = [r.rating_date for r in ratings if r.rating_date]
    stamp = max(dates).isoformat() if dates else datetime.now(UTC).date().isoformat()
    path = directory / f"{stamp}.jsonl.gz"

    receipt = datetime.now(UTC).isoformat()
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for r in ratings:
            handle.write(
                json.dumps(
                    {
                        "morningstar_id": r.morningstar_id,
                        "name": r.name,
                        "category": r.category,
                        "medalist": r.medalist,
                        "star_rating": r.star_rating,
                        "equity_stylebox": r.equity_stylebox,
                        "fixed_income_stylebox": r.fixed_income_stylebox,
                        "event_time": r.rating_date.isoformat() if r.rating_date else None,
                        "knowledge_time": r.rating_date.isoformat() if r.rating_date else None,
                        "receipt_time": receipt,
                        "source": "morningstar.in/featured-reports",
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return path


# --- joining to AMFI, honestly ---------------------------------------------


def _normalise(name: str) -> str:
    """Fold a fund name to something two sources might agree on."""
    text = name.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    for noise in (
        "payout of income dist cum cap wdrl",
        "reinvestment of income dist cum cap wdrl",
        "income dist cum cap wdrl",
        "direct plan",
        "regular plan",
        " fund",
        " scheme",
        " plan",
        " option",
        " growth",
        " idcw",
        " dividend",
    ):
        text = text.replace(noise, " ")
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Join:
    matched: dict[str, str]
    """Morningstar id -> AMFI scheme code, for unambiguous name matches only."""

    ambiguous: int
    unmatched: int

    @property
    def rate(self) -> float:
        total = len(self.matched) + self.ambiguous + self.unmatched
        return len(self.matched) / total if total else 0.0


def join_to_amfi(ratings: list[Rating], schemes: list[object]) -> Join:
    """Match ratings to AMFI schemes by name. **Fuzzy, and labelled as such.**

    Morningstar publishes no ISIN and no scheme code, so a name is the only
    bridge. A name that folds to the same normalised form as two different
    schemes is left **unmatched**, not resolved by picking one: a rating on the
    wrong fund is worse than a rating on none, and this project's identity rule
    exists precisely to stop that trade being made quietly.
    """
    by_name: dict[str, list[str]] = {}
    for scheme in schemes:
        code = str(getattr(scheme, "scheme_code", ""))
        name = str(getattr(scheme, "name", ""))
        if code and name:
            by_name.setdefault(_normalise(name), []).append(code)

    matched: dict[str, str] = {}
    ambiguous = unmatched = 0
    for rating in ratings:
        candidates = by_name.get(_normalise(rating.name), [])
        if len(candidates) == 1:
            matched[rating.morningstar_id] = candidates[0]
        elif candidates:
            ambiguous += 1
        else:
            unmatched += 1
    return Join(matched=matched, ambiguous=ambiguous, unmatched=unmatched)
