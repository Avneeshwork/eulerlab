"""Corporate-actions ingest: yearly buckets, idempotent, no network."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.corp_actions.feed import backfill, fetch_year, url_for_year
from eulerlab.ingest.fetch import Fetcher, FetchPolicy
from eulerlab.ingest.landing import Landing

REAL_SHAPED = (
    b'[{"symbol":"GODREJIND","isin":"INE233A01035","series":"EQ",'
    b'"faceVal":"1","subject":"Bonus 1 : 1250","exDate":"05-Jan-2015",'
    b'"recDate":"06-Jan-2015","bcStartDate":"-","bcEndDate":"-",'
    b'"ndStartDate":"-","ndEndDate":"-","caBroadcastDate":null,'
    b'"comp":"Godrej Industries Limited","ind":"-"}]'
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


def test_url_uses_ddmmyyyy_full_year_bounds() -> None:
    url = url_for_year(2020)
    assert "from_date=01-01-2020" in url
    assert "to_date=31-12-2020" in url


def test_a_good_year_lands(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    result = fetch_year(_fetcher(Serve(REAL_SHAPED)), landing, 2015)
    assert result == "downloaded"
    assert landing.has(date(2015, 1, 1), "corp_actions")


def test_the_second_run_skips(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    fetch_year(_fetcher(Serve(REAL_SHAPED)), landing, 2015)
    assert fetch_year(_fetcher(Serve(REAL_SHAPED)), landing, 2015) == "skipped"


def test_a_404_is_absent_not_failed(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    assert fetch_year(_fetcher(Serve(None, 404)), landing, 2015) == "absent"


def test_an_html_error_page_is_malformed_and_not_landed(tmp_path: Path) -> None:
    """NSE serves some errors as 200 HTML rather than a real status code."""
    landing = Landing(tmp_path)
    served = Serve(b"<html><body>Access Denied</body></html>")
    assert fetch_year(_fetcher(served), landing, 2015) == "malformed"
    assert not landing.has(date(2015, 1, 1), "corp_actions")


def test_a_json_object_instead_of_a_list_is_malformed(tmp_path: Path) -> None:
    result = fetch_year(_fetcher(Serve(b'{"error": "nope"}')), Landing(tmp_path), 2099)
    assert result == "malformed"


def test_backfill_lands_every_year_in_range(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    counts = backfill(_fetcher(Serve(REAL_SHAPED)), landing, from_year=2015, to_year=2017)
    assert counts == {"downloaded": 3}
    for year in (2015, 2016, 2017):
        assert landing.has(date(year, 1, 1), "corp_actions")


def test_backfill_is_idempotent_on_a_second_pass(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    backfill(_fetcher(Serve(REAL_SHAPED)), landing, from_year=2015, to_year=2016)
    counts = backfill(_fetcher(Serve(REAL_SHAPED)), landing, from_year=2015, to_year=2016)
    assert counts == {"skipped": 2}


def _landed_year(root: Path) -> str:
    landing = Landing(root)
    landing.write(
        trade_date=date(2015, 1, 1),
        segment="corp_actions",
        file_format="json",
        url=url_for_year(2015),
        payload=REAL_SHAPED,
        rows=1,
        inner_name="corporate_actions_2015.json",
        suffix="json",
    )
    return next(iter(landing.entries().values())).path


def test_a_pruned_year_is_read_from_the_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-187: the manifest names pruned files; they are read through B2."""
    from eulerlab.corp_actions import build_factors as bf

    root = tmp_path / "nse"
    relative = _landed_year(root)
    (root / relative).chmod(0o644)
    (root / relative).unlink()
    asked: list[str] = []

    def from_bucket(path: str, *, cache: bool = True) -> bytes:
        asked.append(path)
        return REAL_SHAPED

    monkeypatch.setattr("eulerlab.ingest.landing_reader.read", from_bucket)
    actions, _ = bf.load_actions(root)
    assert asked == [f"nse/{relative}"]
    assert [a.isin for a in actions] == ["INE233A01035"]


def test_no_actions_leaves_the_factor_files_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.corp_actions import build_factors as bf

    factors = tmp_path / "price_factors.jsonl"
    factors.write_text("kept\n")
    monkeypatch.setattr(bf, "PRICE_FACTORS", factors)
    monkeypatch.setattr(bf, "TOTAL_RETURN_FACTORS", factors)
    empty = tmp_path / "landing"
    empty.mkdir()
    assert bf.main(["--landing", str(empty), "--manifest", str(empty / "manifest.jsonl")]) == 1
    assert factors.read_text() == "kept\n"


def test_splits_of_a_company_without_an_isin_are_keyed_to_its_own_id(tmp_path: Path) -> None:
    """ADR-187: resolved by symbol on the ex-date through the no-ISIN master."""
    from eulerlab.corp_actions import build_factors as bf
    from eulerlab.corp_actions.parse import parse_rows
    from eulerlab.master import store
    from eulerlab.master.identity import InstrumentId
    from eulerlab.master.registry import Registry

    registry = Registry()
    own = InstrumentId(issuer="NOISIN0123456789")
    for day in (date(2005, 1, 3), date(2005, 12, 30)):
        registry.observe(day, instrument_id=own, ticker="DEADCO", isin="")
    master = tmp_path / "instruments_no_isin.jsonl"
    store.save(registry, store.BuildStamp("x", 1, "2005-01-03", "2005-12-30"), master)

    def row(subject: str, ex: str) -> dict[str, object]:
        return {
            "symbol": "DEADCO",
            "isin": "INE999Z01011",
            "series": "EQ",
            "faceVal": "10",
            "subject": subject,
            "exDate": ex,
        }

    actions, _ = parse_rows(
        [
            row("Fv Split Rs.10/- To Rs.2/-", "01-Jun-2005"),
            row("Dividend - Rs 2 Per Share", "01-Jul-2005"),
            row("Bonus 1:1", "01-Jun-2009"),  # after the company stopped trading
        ]
    )
    copies = bf.no_isin_actions(actions, master)
    assert [(a.isin, a.ex_date) for a in copies] == [("NOISIN0123456789", date(2005, 6, 1))]
