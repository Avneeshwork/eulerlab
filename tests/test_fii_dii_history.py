"""FII/DII backfill: land aggregator pages once, never overwrite NSE, report disagreement.

Every page here is a trimmed copy of a real page fetched on 2026-10-30
(tests/fixtures/fii_dii). No test touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from eulerlab.ingest import fii_dii_cash as cash
from eulerlab.ingest import fii_dii_history as h
from eulerlab.ingest.fetch import Fetcher, FetchPolicy
from eulerlab.ingest.landing import Landing

FIXTURES = Path(__file__).parent / "fixtures" / "fii_dii"
TRENDLYNE_SEP = (FIXTURES / "trendlyne_cash-pastmonth_30-Sep-2026.html").read_bytes()
GROWW = (FIXTURES / "groww_fii-dii-data_2026-10-30.html").read_bytes()
STOCKEZEE = (FIXTURES / "stockezee_fii-dii-historical-data_2026-10-30.html").read_bytes()
NSE = (FIXTURES / "nse_fiidiiTradeReact_2026-10-29.json").read_bytes()
TODAY = date(2026, 10, 30)


class Site:
    """Serves the saved pages by URL; anything else is a 404."""

    def __init__(self, pages: dict[str, tuple[int, bytes]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        self.calls.append(url)
        return self.pages.get(url, (404, b""))


def _fetcher(site: Site) -> Fetcher:
    return Fetcher(site, FetchPolicy(min_interval_s=0.0, max_attempts=1), sleep=lambda _: None)


def _read(root: Path) -> Callable[[str], bytes]:
    return lambda rel: (root.parent / rel).read_bytes()


def _site(status: int = 200) -> Site:
    return Site(
        {
            h.trendlyne_url(date(2026, 9, 30)): (status, TRENDLYNE_SEP),
            h.GROWW_URL: (200, GROWW),
            h.STOCKEZEE_URL: (200, STOCKEZEE),
        }
    )


def test_trendlyne_reads_the_cash_table_and_not_the_others() -> None:
    parsed = h.parse_trendlyne(TRENDLYNE_SEP)
    assert parsed is not None and not parsed.refused
    days = {d.trade_date: d for d in parsed.days}
    assert min(days) == date(2026, 8, 31) and max(days) == date(2026, 9, 30)
    sep30 = days[date(2026, 9, 30)]
    # The DII columns run net, sales, purchase on this page.
    assert (sep30.fii.buy, sep30.fii.sell, sep30.fii.net) == (14967.8, 25116.2, -10148.4)
    assert (sep30.dii.buy, sep30.dii.sell, sep30.dii.net) == (24413.8, 13142.0, 11271.7)


def test_trendlyne_rounding_is_allowed_but_a_wrong_column_is_not() -> None:
    # 15-Sep: 13194.8 - 16172.6 = -2977.8 against -2977.9, a 0.1 rounding gap.
    parsed = h.parse_trendlyne(TRENDLYNE_SEP)
    assert parsed is not None
    assert date(2026, 9, 15) in {d.trade_date for d in parsed.days}
    broken = TRENDLYNE_SEP.replace(b"-10148.4", b"-10048.4")
    again = h.parse_trendlyne(broken)
    assert again is not None and any("2026-09-30" in r for r in again.refused)


def test_a_page_without_the_cash_table_is_refused() -> None:
    assert h.parse_trendlyne(b"<html>Access denied</html>") is None
    assert h.parse_trendlyne(TRENDLYNE_SEP.replace(b"FII Gross Purchase", b"FII Buy")) is None
    assert h.parse_groww(b"<html></html>") is None
    assert h.parse_stockezee(b"<html></html>") is None


def test_groww_and_stockezee_parse_their_real_pages() -> None:
    groww = h.parse_groww(GROWW)
    assert groww is not None and len(groww.days) == 20 and not groww.refused
    oct29 = {d.trade_date: d for d in groww.days}[date(2026, 10, 29)]
    nse = cash.parse(NSE)
    assert nse is not None and oct29 == nse  # Groww republishes NSE to the paisa
    ezee = h.parse_stockezee(STOCKEZEE)
    assert ezee is not None and ezee.nets[date(2026, 9, 30)] == (-10148.41, 11271.73)


def test_real_nse_payload_parses() -> None:
    day = cash.parse(NSE)
    assert day is not None and day.trade_date == date(2026, 10, 29)
    assert (day.fii.buy, day.fii.sell, day.fii.net) == (13400.29, 14343.89, -943.6)
    assert (day.dii.buy, day.dii.sell, day.dii.net) == (18458.64, 16534.23, 1924.41)


def test_page_dates_cover_the_months_and_end_today() -> None:
    dates = h.page_dates(TODAY, 12)
    assert dates[0] == date(2025, 10, 31) and dates[-2] == date(2026, 9, 30)
    assert dates[-1] == TODAY and len(dates) == 13
    assert h.page_dates(date(2026, 1, 5), 1) == [date(2025, 12, 31), date(2026, 1, 5)]
    assert h.trendlyne_url(date(2025, 11, 30)).endswith("/cash-pastmonth/30-Nov-2025/")


def test_trading_day_rule() -> None:
    known = frozenset({date(2026, 9, 1), date(2026, 9, 2)})
    assert h.is_trading_day(date(2026, 9, 1), known, TODAY)
    assert not h.is_trading_day(date(2026, 8, 31), known, TODAY)  # inside, not a bhavcopy day
    assert h.is_trading_day(date(2026, 10, 1), known, TODAY)  # past the manifest: a weekday
    assert not h.is_trading_day(date(2026, 10, 4), known, TODAY)  # a Sunday
    assert not h.is_trading_day(date(2026, 11, 2), known, TODAY)  # the future


def test_backfill_lands_once_and_never_overwrites_nse(tmp_path: Path) -> None:
    root, derived = tmp_path / "fii_dii", tmp_path / "derived.jsonl"
    landing = Landing(root)
    # NSE's own capture of 30-Sep, with a figure that differs from Trendlyne's.
    nse_sep30 = cash.FlowDay(
        trade_date=date(2026, 9, 30),
        fii=cash.Flow(buy=14967.84, sell=25116.20, net=-10148.36),
        dii=cash.Flow(buy=24413.80, sell=13142.00, net=11271.80),
    )
    cash.append(nse_sep30, "2026-09-30T14:00:00+00:00", derived)

    site = _site()
    report = h.backfill(
        _fetcher(site), landing, _read(root), today=TODAY, months=1, derived=derived
    )
    # Trendlyne's 30-Sep page, today's page (a 404 here), Groww, stockezee.
    assert report.fetched == 3 and len(report.failed) == 1 and not report.stopped
    assert report.written == 21 and report.held == 1
    held = {r["day"]: r for r in cash.rows(derived)}
    assert held["2026-09-30"]["source"] == "nse"
    assert held["2026-09-30"]["fii_net"] == -10148.36
    assert held["2026-09-01"]["source"] == "trendlyne"
    assert report.compared["trendlyne~nse"] == 1
    assert not report.disagreements  # within a crore

    calls = len(site.calls)
    again = h.backfill(_fetcher(site), landing, _read(root), today=TODAY, months=1, derived=derived)
    assert again.written == 0 and again.skipped == 3
    assert len(site.calls) == calls + 1  # only the page that 404ed is asked again


def test_disagreement_over_a_crore_is_reported(tmp_path: Path) -> None:
    root, derived = tmp_path / "fii_dii", tmp_path / "derived.jsonl"
    wrong = cash.FlowDay(
        trade_date=date(2026, 9, 29),
        fii=cash.Flow(buy=22472.7, sell=32452.9, net=-9980.2),
        dii=cash.Flow(buy=46261.1, sell=39000.0, net=7261.1),
    )
    cash.append(wrong, "2026-09-29T14:00:00+00:00", derived)
    report = h.backfill(
        _fetcher(_site()), Landing(root), _read(root), today=TODAY, months=1, derived=derived
    )
    assert any(d.startswith("2026-09-29 dii_sell") for d in report.disagreements)
    assert any(d.startswith("2026-09-29 dii_net") for d in report.disagreements)


def test_a_refusal_stops_the_run(tmp_path: Path) -> None:
    root = tmp_path / "fii_dii"
    site = _site(status=429)
    report = h.backfill(
        _fetcher(site),
        Landing(root),
        _read(root),
        today=TODAY,
        months=1,
        derived=tmp_path / "d.jsonl",
    )
    assert "429" in report.stopped
    assert site.calls == [h.trendlyne_url(date(2026, 9, 30))]
    assert not (root / "manifest.jsonl").exists()


def test_backfilled_rows_are_not_known_before_the_scrape(tmp_path: Path) -> None:
    root, derived = tmp_path / "fii_dii", tmp_path / "derived.jsonl"
    h.backfill(
        _fetcher(_site()), Landing(root), _read(root), today=TODAY, months=1, derived=derived
    )
    assert cash.rows(derived, as_of=datetime.fromisoformat("2026-10-01T00:00:00+00:00")) == []
    assert len(cash.rows(derived)) == 22


def test_rebuild_keeps_backfilled_days_and_is_byte_identical(tmp_path: Path) -> None:
    root, derived = tmp_path / "fii_dii", tmp_path / "derived.jsonl"
    landing = Landing(root)
    h.backfill(_fetcher(_site()), landing, _read(root), today=TODAY, months=1, derived=derived)
    cash.rebuild(Landing(root), _read(root), derived)
    first = derived.read_bytes()
    cash.rebuild(Landing(root), _read(root), derived)
    assert derived.read_bytes() == first
    lines = [json.loads(x) for x in first.decode().splitlines()]
    assert len(lines) == 22 and {r["source"] for r in lines} == {"trendlyne"}
