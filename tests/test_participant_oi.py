"""Participant-OI ingest: never land something that is not the report."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from eulerlab.ingest.fetch import Fetcher, FetchPolicy
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.participant_oi import fetch_day, parse, url_for

# Shape observed from the live file on 2026-08-18: a title line, then a header.
REAL = (
    b'""Participant wise Open Interest (no. of contracts) as on Aug 14, 2026"",,,\n'
    b"Client Type,Future Index Long,Future Index Short,Total Long Contracts\n"
    b"Client,211638,55956,13152111\n"
    b"DII,50830,20040,479918\n"
    b"FII,120000,90000,900000\n"
    b"Pro,10000,9000,80000\n"
    b"TOTAL,392468,174996,14612029\n"
)


class Serve:
    def __init__(self, payload: bytes | None, status: int = 200) -> None:
        self.payload, self.status = payload, status

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        return self.status, (self.payload or b"")


def _fetcher(transport: object) -> Fetcher:
    return Fetcher(
        transport,  # type: ignore[arg-type]
        FetchPolicy(min_interval_s=0.0, max_attempts=1),
        sleep=lambda _: None,
    )


def test_url_uses_ddmmyyyy() -> None:
    assert url_for(date(2026, 8, 14)).endswith("fao_participant_oi_14082026.csv")


def test_day_is_zero_padded() -> None:
    assert "01042020" in url_for(date(2020, 4, 1))


def test_parses_past_the_title_line() -> None:
    parsed = parse(REAL)
    assert parsed is not None
    assert parsed.rows == 5
    assert "FII" in parsed.client_types
    assert parsed.looks_sane


def test_a_file_without_the_expected_participants_is_not_sane() -> None:
    payload = b"Client Type,Future Index Long\nSomethingElse,1\n"
    parsed = parse(payload)
    assert parsed is not None
    assert not parsed.looks_sane


def test_a_non_report_returns_none() -> None:
    assert parse(b"<html><body>Access Denied</body></html>") is None


def test_a_good_day_lands(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    assert fetch_day(_fetcher(Serve(REAL)), landing, date(2026, 8, 14)) == "downloaded"
    assert landing.has(date(2026, 8, 14), "participant_oi")


def test_the_second_run_skips(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    fetch_day(_fetcher(Serve(REAL)), landing, date(2026, 8, 14))
    assert fetch_day(_fetcher(Serve(REAL)), landing, date(2026, 8, 14)) == "skipped"


def test_a_holiday_is_absent_not_failed(tmp_path: Path) -> None:
    assert fetch_day(_fetcher(Serve(None, 404)), Landing(tmp_path), date(2026, 8, 15)) == "absent"


def test_an_error_page_is_malformed_and_is_not_landed(tmp_path: Path) -> None:
    """A 200 carrying an error page must not become a file that looks like data."""
    landing = Landing(tmp_path)
    served = Serve(b"<html>Service Unavailable</html>")
    assert fetch_day(_fetcher(served), landing, date(2026, 8, 14)) == "malformed"
    assert not landing.has(date(2026, 8, 14), "participant_oi")


def test_landed_file_keeps_the_csv_suffix(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    fetch_day(_fetcher(Serve(REAL)), landing, date(2026, 8, 14))
    entry = next(iter(landing.entries().values()))
    assert entry.path.endswith(".csv")


# --- series-suffixed tickers must still resolve ---


def test_a_series_suffixed_symbol_resolves_from_its_bare_ticker() -> None:
    """NSE renames a surveillance-listed stock to TICKER-BE in Kite.

    Four symbols (RELINFRA, STLTECH, DIACABS, MTARTECH) were reported as
    delisted because the lookup matched the bare ticker only. They were listed
    the whole time, in the BE series.
    """
    from eulerlab.ingest.kite_minute import parse_instruments

    csv_text = (
        b"instrument_token,tradingsymbol,name,exchange,instrument_type\n"
        b"111,RELINFRA-BE,Reliance Infra,NSE,EQ\n"
        b"222,RELIANCE,Reliance,NSE,EQ\n"
    )

    mapping = parse_instruments(csv_text)

    assert mapping["RELINFRA"] == 111
    assert mapping["RELIANCE"] == 222


def test_a_plain_listing_wins_over_a_suffixed_one() -> None:
    from eulerlab.ingest.kite_minute import parse_instruments

    csv_text = (
        b"instrument_token,tradingsymbol,name,exchange,instrument_type\n"
        b"111,ACME-BE,Acme,NSE,EQ\n"
        b"222,ACME,Acme,NSE,EQ\n"
    )

    assert parse_instruments(csv_text)["ACME"] == 222
