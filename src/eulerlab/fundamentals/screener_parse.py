"""Parse screener.in company pages into tidy rows.

**Provenance warning.** This data is collected against screener.in's stated
terms, which permit "personal, non-commercial transitory viewing only" and
forbid copying or mirroring. The operator was shown the clause and decided to
proceed; see ADR-011. Nothing here is redistributed, and the constraint matters
downstream: results built on this data carry a source that could disappear.

Parsing notes, from reading the real markup rather than guessing:

* Each statement lives in a ``<section id="...">`` — ``quarters``,
  ``profit-loss``, ``balance-sheet``, ``cash-flow``, ``ratios``,
  ``shareholding``.
* Most column headers carry ``data-date-key="YYYY-MM-DD"``, which is the period
  end date in ISO form — far more reliable than parsing the visible "Jun 2023"
  label. The shareholding tables are the exception: they use plain ``<th>Jun
  2023</th>`` with no date key, so those headers are parsed from the label and
  normalised to a month-end date.
* Row labels contain markup and footnote symbols; they are cleaned to plain
  text so they can be used as stable field names.

The parser is deliberately tolerant: a section that is absent (not every
company has every statement) yields no rows rather than raising, because one
missing balance sheet must not abort a 400-company run.
"""

from __future__ import annotations

import calendar
import html
import re
from dataclasses import dataclass

SECTIONS = (
    "quarters",
    "profit-loss",
    "balance-sheet",
    "cash-flow",
    "ratios",
    "shareholding",
)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Profile:
    """Page-level facts that are not part of any statement table.

    Sector and index membership matter more than they look: without a sector
    tag, a "momentum" factor is frequently an unintended sector bet, and
    sector-neutralising is the standard fix. Index membership here is *today\'s*
    membership — screener shows current constituents, not history — so it is
    only point-in-time in the sense that repeated dated snapshots build a
    membership history going forward. It must never be applied backwards.
    """

    name: str | None = None
    sectors: tuple[str, ...] = ()
    indices: tuple[str, ...] = ()
    ratios: tuple[tuple[str, str], ...] = ()
    """The header summary: Market Cap, Stock P/E, Book Value, Dividend Yield..."""


@dataclass(frozen=True)
class Cell:
    """One value: which statement, which line item, which period."""

    section: str
    row_label: str
    period: str
    value: float | None
    raw: str


def _text(fragment: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", fragment))).strip()


def _to_float(raw: str) -> float | None:
    """Screener renders numbers with commas, %, and sometimes a trailing +.

    Returns None rather than 0.0 for unparseable cells — a missing value and a
    zero are different facts, and conflating them silently corrupts any ratio
    computed downstream.
    """
    cleaned = raw.replace(",", "").replace("%", "").replace("+", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _section_html(page: str, section_id: str) -> str | None:
    marker = f'id="{section_id}"'
    start = page.find(marker)
    if start == -1:
        return None
    # Take a generous slice; the table parser stops at </table> anyway.
    return page[start : start + 120_000]


_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _label_to_period(label: str) -> str | None:
    """ "Jun 2023" -> "2023-06-30". Used only where data-date-key is absent.

    Screener's statement columns are period *ends*, so the month's last day is
    the correct normalisation, not the first.
    """
    match = re.match(r"([A-Za-z]{3})\s+(\d{4})$", label.strip())
    if match is None:
        return None
    month = _MONTHS.get(match.group(1).title())
    if month is None:
        return None
    year = int(match.group(2))
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


def _periods(table_html: str) -> list[str]:
    keyed = re.findall(r'data-date-key="(\d{4}-\d{2}-\d{2})"', table_html)
    if keyed:
        return keyed
    # Shareholding tables carry no date keys; fall back to the visible labels.
    head = re.search(r"<thead[^>]*>(.*?)</thead>", table_html, re.DOTALL)
    if head is None:
        return []
    labels = [_text(th) for th in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.DOTALL)]
    return [p for p in (_label_to_period(lbl) for lbl in labels) if p]


def parse_section(page: str, section_id: str) -> list[Cell]:
    """Rows for one statement. Empty list when the section is absent."""
    section = _section_html(page, section_id)
    if section is None:
        return []

    table_match = re.search(r"<table[^>]*>(.*?)</table>", section, re.DOTALL)
    if table_match is None:
        return []
    table = table_match.group(1)

    periods = _periods(table)
    if not periods:
        return []

    cells: list[Cell] = []
    body = table.split("</thead>", 1)[-1]
    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL):
        row = row_match.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 2:
            continue
        label = _text(tds[0]).rstrip("+").strip()
        if not label:
            continue
        for period, raw_cell in zip(periods, tds[1:], strict=False):
            raw = _text(raw_cell)
            cells.append(
                Cell(
                    section=section_id,
                    row_label=label,
                    period=period,
                    value=_to_float(raw),
                    raw=raw,
                )
            )
    return cells


def parse_page(page: str) -> list[Cell]:
    """Every statement on a company page, flattened."""
    out: list[Cell] = []
    for section_id in SECTIONS:
        out.extend(parse_section(page, section_id))
    return out


def company_name(page: str) -> str | None:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.DOTALL)
    return _text(match.group(1)) if match else None


# Screener renders index tags and sector tags with the same CSS class, so they
# are separated by name. Anything matching a known index family is an index;
# the rest is sector/industry classification.
_INDEX_MARKERS = ("nifty", "bse ", "sensex", "dollex")


def _looks_like_index(tag: str) -> bool:
    lowered = tag.lower()
    return any(marker in lowered for marker in _INDEX_MARKERS)


def parse_top_ratios(page: str) -> tuple[tuple[str, str], ...]:
    """The header summary block: Market Cap, Stock P/E, Book Value, ROCE...

    Kept as (label, raw) string pairs rather than parsed floats. These mix
    currencies, percentages and ranges ("High / Low 1,612 / 1,250"), so
    coercing them here would either lose information or invent a schema; the
    consumer decides what it wants.
    """
    start = page.find('id="top-ratios"')
    if start == -1:
        return ()
    block = page[start : start + 6000]
    pairs: list[tuple[str, str]] = []
    for item in re.finditer(r"<li[^>]*>(.*?)</li>", block, re.DOTALL):
        name_match = re.search(r'class="name"[^>]*>(.*?)<', item.group(1), re.DOTALL)
        if name_match is None:
            continue
        label = _text(name_match.group(1)).rstrip(":").strip()
        value = _text(item.group(1))
        if label and value.startswith(label):
            value = value[len(label) :].strip()
        if label:
            pairs.append((label, value))
    return tuple(pairs)


def parse_profile(page: str) -> Profile:
    """Name, sector/industry tags, index membership and header ratios."""
    tags: list[str] = []
    sectors: list[str] = []
    start = page.find('id="peers"')
    if start != -1:
        block = page[start : start + 4000]
        # Sector hierarchy is a breadcrumb of /market/ links carrying a title
        # attribute ("Broad Sector" -> "Sector" -> "Industry"), ordered broad
        # to narrow. Keeping the order preserves the hierarchy.
        for match in re.finditer(r'<a[^>]+href="/market/[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL):
            sector = _text(match.group(1))
            if sector and sector not in sectors:
                sectors.append(sector)
        for match in re.finditer(r'class="tag[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL):
            tag = _text(match.group(1))
            if tag and tag not in tags:
                tags.append(tag)

    return Profile(
        name=company_name(page),
        sectors=tuple(sectors),
        indices=tuple(t for t in tags if _looks_like_index(t)),
        ratios=parse_top_ratios(page),
    )
