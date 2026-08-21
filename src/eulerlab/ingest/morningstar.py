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
from collections.abc import Sequence
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
    detail_path: str = ""
    """Path to the fund's own page, which is where the ISIN lives.

    Optional, because the page resolves on the id alone — the slug in the URL
    is decorative and any value returns the right fund. That matters more than
    it sounds: it means the ISIN crawl can be driven from a landed ratings file
    and never has to re-walk the listing, whose pagination is flaky (it
    completed all 29 pages once and stalled at page 4 the next time).
    """

    @property
    def path(self) -> str:
        """Where to fetch this fund's own page."""
        return self.detail_path or f"/mutualfunds/{self.morningstar_id}/x/morningstar-analysis.aspx"


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
        link = re.search(r"href='(/mutualfunds/(f[0-9a-z]+)/[^']*)'\s*title='([^']*)'", row)
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
                morningstar_id=link.group(2),
                name=html.unescape(link.group(3)).strip(),
                detail_path=html.unescape(link.group(1)),
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

    def open_path(self, path: str, *, timeout: int = 45) -> str:
        """GET a page other than the listing (a fund's own page)."""
        url = urllib.parse.urljoin("https://www.morningstar.in", path)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with self._opener.open(request, timeout=timeout) as response:
            body: bytes = response.read()
            return body.decode("utf-8", errors="replace")

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


ISIN_PATH = Path("data/landing/mf/morningstar_isin.jsonl")
ISIN_RE = re.compile(r"\bINF[0-9A-Z]{9}\b")


def parse_isin(page: str) -> str:
    """The scheme's ISIN, from its own Morningstar page.

    The listing page carries no ISIN at all — only a name — which is what
    forced the fuzzy name join and capped it at 18.3%. The per-fund page does
    carry one, and an ISIN is a real instrument identifier rather than a label,
    so joining on it satisfies the rule the name join could only apologise for.
    """
    match = ISIN_RE.search(page)
    return match.group(0) if match else ""


def read_landed(path: Path) -> list[Rating]:
    """Ratings from a landed snapshot, so a crawl need not re-walk the listing."""
    out: list[Rating] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            out.append(
                Rating(
                    morningstar_id=str(row["morningstar_id"]),
                    name=str(row["name"]),
                    category=str(row.get("category") or ""),
                    medalist=str(row.get("medalist") or ""),
                    star_rating=row.get("star_rating"),
                    equity_stylebox=row.get("equity_stylebox"),
                    fixed_income_stylebox=row.get("fixed_income_stylebox"),
                    rating_date=None,
                )
            )
    return out


def known_isins(*, path: Path = ISIN_PATH) -> dict[str, str]:
    """Morningstar id -> ISIN for everything already fetched.

    This is what makes the crawl resumable: 5,741 detail pages is over an hour,
    and a run that had to start again from zero would never finish.
    """
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[str(row["morningstar_id"])] = str(row["isin"])
    return out


def fetch_isins(
    ratings: list[Rating],
    *,
    path: Path = ISIN_PATH,
    pace: float = 0.8,
    limit: int = 0,
) -> dict[str, str]:
    """Walk the fund pages and record each ISIN, skipping what is already known.

    An empty ISIN is recorded too, deliberately. Without it a fund whose page
    genuinely has none would be retried on every future run forever.
    """
    known = known_isins(path=path)
    todo = [r for r in ratings if r.morningstar_id not in known]
    if limit:
        todo = todo[:limit]

    path.parent.mkdir(parents=True, exist_ok=True)
    session = _Session()
    for index, rating in enumerate(todo, start=1):
        try:
            page = session.open_path(rating.path)
            isin = parse_isin(page)
        except Exception:
            isin = ""
        known[rating.morningstar_id] = isin
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"morningstar_id": rating.morningstar_id, "isin": isin}, sort_keys=True)
                + "\n"
            )
        if index % 200 == 0 or index == len(todo):
            found = sum(1 for v in known.values() if v)
            print(f"  [{index:>5}/{len(todo)}] {found:,} ISINs known")
        time.sleep(pace)
    return known


ENRICHED_DIR = Path("data/landing/mf/enriched")


def land_enriched(rows: list[dict[str, object]], *, directory: Path = ENRICHED_DIR) -> Path:
    """Write the AMFI-spine view with ratings attached.

    A derived artefact rather than raw landing — it is reproducible from the
    two snapshots it was built from, and is written beside them so the daily
    job produces one file a reader can actually use.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).date().isoformat()
    path = directory / f"{stamp}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


# --- joining to AMFI, honestly ---------------------------------------------


_PLAN_WORDS = (("direct", "direct"), ("regular", "regular"), ("reg", "regular"))
"""Morningstar abbreviates: "Fund - Reg Pr" is a Regular plan. Matched on word
boundaries so `reg` cannot fire inside "Regency" or "Aggressive"."""

_OPTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("idcw-reinvest", ("re-investment", "reinvestment", "re investment", "reinvest")),
    ("idcw-payout", ("payout",)),
    ("growth", ("growth",)),
    ("idcw", ("idcw", "dividend", "dcw")),
)
"""Order matters: a name saying "Reinvestment of Income Dist cum Cap Wdrl" also
contains no "growth", but "IDCW-Re-investment" must not fall through to the
bare `idcw` bucket. Most specific first."""

_TAIL = re.compile(
    r"\b("
    r"p(?:y)?t\s+of\s+inc|payout\s+of\s+inc|"
    r"r(?:ei)?nvmt\s+of\s+inc|reinvestment\s+of\s+inc|re\s*investment\s+of\s+inc|"
    r"prdic\s+r|of\s+inc(?:ome)?\s+dist|inc(?:ome)?\s+dist|dist\s+cum\s+cap|idcw|dividend"
    r").*$",
    re.I,
)
"""Everything from a distribution phrase to the end of the name is noise.

Morningstar abbreviates these a dozen ways — "Pyt of Inc Dis cum Cap Wdrl",
"Rnvmt of Inc DiscumcptlWdrlOpt", "Prdic Rnvmt of Inc Dis cumcptlwdrlopt" —
and AMFI does not put any of them in its `name` column at all. Matching the
phrase and cutting to the end is far more robust than enumerating spellings:
that enumeration is what left 4,305 funds unmatched.

`inc` and `income` are both spelled out because Morningstar uses each. Matching
only the long form left 2,691 funds carrying a trailing "inc dist cum cap wdrl"
that AMFI never writes, so their base names could not agree.
"""

_FREQUENCY = ("daily", "weekly", "fortnightly", "monthly", "quarterly", "half yearly", "annual")

_NOISE = (
    "direct plan",
    "regular plan",
    "growth option",
    "idcw option",
)


def _base_name(name: str) -> str:
    """Fold a fund name to the part both sources spell the same way.

    AMFI keeps plan and option in their own columns, so its `name` is already
    the base. Morningstar concatenates all three, so the plan and option words
    are stripped here — but captured separately by `_plan` / `_option` rather
    than discarded, because throwing them away is what collapsed 594 distinct
    schemes onto one ambiguous name.
    """
    text = name.lower()
    for noise in _NOISE:
        text = text.replace(noise, " ")
    text = _TAIL.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    for freq in _FREQUENCY:
        text = re.sub(rf"\b{freq}\b", " ", text)
    for word in (
        "fund",
        "scheme",
        "plan",
        "option",
        "growth",
        "idcw",
        "dividend",
        "direct",
        "regular",
        "payout",
        "reinvestment",
    ):
        text = re.sub(rf"\b{word}\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _plan(text: str) -> str:
    lowered = text.lower()
    for needle, label in _PLAN_WORDS:
        if re.search(rf"\b{needle}\b", lowered):
            return label
    return ""


def _option(text: str) -> str:
    lowered = text.lower()
    for label, needles in _OPTION_PATTERNS:
        if any(n in lowered for n in needles):
            return label
    return ""


def _coarse(option: str) -> str:
    """Collapse the payout/reinvestment split back to plain IDCW.

    AMFI usually records the option as bare `IDCW` (3,670 schemes) and only
    sometimes distinguishes payout from reinvestment (310 and 312).
    Morningstar always distinguishes. Demanding exact equality therefore fails
    on ~2,700 funds that are in fact the same scheme, so the join tries the
    exact option first and falls back to this coarser bucket.
    """
    return "idcw" if option.startswith("idcw") else option


def _key(name: str, plan: str = "", option: str = "") -> tuple[str, str, str]:
    """The composite identity two sources can agree on.

    Not an internal id, and this is not pretending to be one — see ADR-039.
    It is a name plus the two attributes that distinguish a scheme's variants,
    which is the most a source without an ISIN can offer.
    """
    return (_base_name(name), _plan(plan or name), _option(option or name))


@dataclass(frozen=True)
class Join:
    matched: dict[str, str]
    """Morningstar id -> **ISIN**, not scheme code.

    The grain matters and got this wrong once. AMFI publishes two ISINs per
    `scheme_code` — the payout one and the reinvestment one — while Morningstar
    treats those as two funds. Joining to the scheme code therefore made two
    legitimate ratings collide on one key, and the one-to-one guard dropped
    both as contested. They were not contested; they were two instruments
    inside one scheme. The ISIN is the instrument.
    """

    ambiguous: int
    unmatched: int
    by_isin: int = 0
    """How many matched on ISIN. The rest, if any, are name matches."""

    @property
    def rate(self) -> float:
        total = len(self.matched) + self.ambiguous + self.unmatched
        return len(self.matched) / total if total else 0.0


def _primary_isin(code: str, schemes: Sequence[object]) -> str:
    for scheme in schemes:
        if str(getattr(scheme, "scheme_code", "")) == code:
            return str(getattr(scheme, "isin_growth", "") or "")
    return ""


def join_to_amfi(
    ratings: list[Rating],
    schemes: Sequence[object],
    *,
    isins: dict[str, str] | None = None,
) -> Join:
    """Match ratings to AMFI schemes.

    **On ISIN when one is known, which is the whole point.** An ISIN is a real
    instrument identifier, so a match on it satisfies `CLAUDE.md`'s rule that
    joins use identifiers and never labels. AMFI publishes two per scheme — the
    growth/payout ISIN and the reinvestment one — and either may be the one
    Morningstar shows, so both are indexed.

    A fund with no ISIN falls back to the composite name key, which is fuzzy and
    capped around 18%. That fallback is kept rather than dropped because some
    funds genuinely have no ISIN on their page, but it is counted separately so
    the two are never confused in a report.

    Matches are one-to-one in both directions. If two ratings claim one scheme,
    neither is kept: a rating on the wrong fund is worse than a rating on none.
    """
    isins = isins or {}

    by_isin: dict[str, list[str]] = {}
    by_key: dict[tuple[str, str, str], list[str]] = {}
    for scheme in schemes:
        code = str(getattr(scheme, "scheme_code", ""))
        name = str(getattr(scheme, "name", ""))
        if not code:
            continue
        for field in ("isin_growth", "isin_reinvest"):
            value = str(getattr(scheme, field, "") or "")
            if value:
                by_isin.setdefault(value, []).append(code)
        if name:
            key = _key(name, str(getattr(scheme, "plan", "")), str(getattr(scheme, "option", "")))
            by_key.setdefault(key, []).append(code)

    by_coarse: dict[tuple[str, str, str], list[str]] = {}
    for key, codes in by_key.items():
        by_coarse.setdefault((key[0], key[1], _coarse(key[2])), []).extend(codes)

    matched: dict[str, str] = {}
    isin_hits = 0
    ambiguous = unmatched = 0

    for rating in ratings:
        isin = isins.get(rating.morningstar_id, "")
        candidates = by_isin.get(isin, []) if isin else []
        hit_by_isin = len(candidates) == 1

        if not hit_by_isin:
            key = _key(rating.name)
            candidates = by_key.get(key, [])
            if len(candidates) != 1:
                coarse = by_coarse.get((key[0], key[1], _coarse(key[2])), [])
                candidates = coarse if len(coarse) == 1 else candidates or coarse

        if hit_by_isin:
            matched[rating.morningstar_id] = isin
            isin_hits += 1
        elif len(candidates) == 1:
            # No ISIN on the fund's page. Fall back to the name key and record
            # the scheme's primary ISIN, so every matched row is keyed the same
            # way regardless of how it was found.
            primary = _primary_isin(candidates[0], schemes)
            if primary:
                matched[rating.morningstar_id] = primary
            else:
                unmatched += 1
        elif candidates:
            ambiguous += 1
        else:
            unmatched += 1

    # One-to-one in the other direction too. The name fallback can send several
    # Morningstar variants at one scheme, and keeping whichever arrived last
    # would attach an arbitrary rating to a real fund.
    claims: dict[str, list[str]] = {}
    for mid, code in matched.items():
        claims.setdefault(code, []).append(mid)
    contested = {mid for mids in claims.values() if len(mids) > 1 for mid in mids}
    for mid in contested:
        del matched[mid]
    ambiguous += len(contested)
    isin_hits = min(isin_hits, len(matched))

    return Join(matched=matched, ambiguous=ambiguous, unmatched=unmatched, by_isin=isin_hits)


def enrich(
    schemes: Sequence[object],
    ratings: list[Rating],
    join: Join,
    *,
    isins: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """AMFI records with Morningstar ratings attached where they matched.

    **AMFI is the spine.** Every scheme AMFI publishes appears exactly once,
    whether or not a rating was found; a fund with no rating carries nulls
    rather than being dropped. The reverse — Morningstar as the spine — would
    silently shrink the universe to whatever a third party happens to cover.

    Every enriched row carries `rating_join` so a reader can tell a matched
    rating from an absent one without inferring it from a null, and knows the
    match was by name rather than by identifier (ADR-039).
    """
    by_isin_key = {isin: mid for mid, isin in join.matched.items()}
    by_mid = {r.morningstar_id: r for r in ratings}
    known = isins or {}

    out: list[dict[str, object]] = []
    for scheme in schemes:
        code = str(getattr(scheme, "scheme_code", ""))
        isin = str(getattr(scheme, "isin_growth", "") or "")
        rating = by_mid.get(by_isin_key.get(isin, ""))
        out.append(
            {
                "scheme_code": code,
                "isin": isin,
                "name": getattr(scheme, "name", ""),
                "amc": getattr(scheme, "amc", ""),
                "plan": getattr(scheme, "plan", ""),
                "option": getattr(scheme, "option", ""),
                "nav": getattr(scheme, "nav", None),
                "morningstar_id": rating.morningstar_id if rating else None,
                "star_rating": rating.star_rating if rating else None,
                "medalist": rating.medalist if rating else None,
                "category": rating.category if rating else None,
                # How the row was joined, not merely that it was. An ISIN
                # match is an identifier match; a name match is an educated
                # guess, and a reader must be able to tell them apart.
                "rating_join": (
                    "isin"
                    if rating and known.get(rating.morningstar_id)
                    else ("name-fuzzy" if rating else "none")
                ),
            }
        )
    return out
