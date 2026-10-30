"""FII/DII cash flows: land NSE's day under its own date, once, and never garbage."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from eulerlab.ingest import fii_dii_cash as f
from eulerlab.ingest.fetch import Fetcher, FetchPolicy
from eulerlab.ingest.landing import Landing


def _payload(
    day: str = "17-Aug-2026",
    fii: tuple[str, str, str] = ("11546.16", "14081.26", "-2535.10"),
    dii: tuple[str, str, str] = ("16654.08", "11552.62", "5101.46"),
) -> bytes:
    # The figures research 004 read from NSE for 17 Aug 2026, in NSE's real
    # shape (A-070). The real response is in tests/fixtures/fii_dii; this one
    # stays because the refusal tests need payloads NSE would not send.
    rows = [
        {
            "category": "DII **",
            "date": day,
            "buyValue": dii[0],
            "sellValue": dii[1],
            "netValue": dii[2],
        },
        {
            "category": "FII/FPI **",
            "date": day,
            "buyValue": fii[0],
            "sellValue": fii[1],
            "netValue": fii[2],
        },
    ]
    return json.dumps(rows).encode()


class Serve:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload, self.status, self.calls = payload, status, 0

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        self.calls += 1
        return self.status, self.payload


def _fetcher(transport: object) -> Fetcher:
    return Fetcher(
        transport,  # type: ignore[arg-type]
        FetchPolicy(min_interval_s=0.0, max_attempts=1),
        sleep=lambda _: None,
    )


def test_parses_both_groups_under_the_payloads_own_date() -> None:
    day = f.parse(_payload())
    assert day is not None
    assert day.trade_date == date(2026, 8, 17)
    assert day.fii.net == -2535.10
    assert day.dii.buy == 16654.08


@pytest.mark.parametrize(
    "payload",
    [
        b"<html>Access Denied</html>",
        b"{}",
        b"[]",
        json.dumps(
            [
                {
                    "category": "DII",
                    "date": "17-Aug-2026",
                    "buyValue": 1,
                    "sellValue": 1,
                    "netValue": 0,
                }
            ]
        ).encode(),
        _payload(fii=("100", "50", "10")),  # net is not buy - sell
        _payload(dii=("-5", "1", "-6")),  # negative turnover
    ],
)
def test_refuses_what_is_not_one_days_report(payload: bytes) -> None:
    assert f.parse(payload) is None


def test_refuses_two_groups_on_different_days() -> None:
    rows = json.loads(_payload())
    rows[0]["date"] = "14-Aug-2026"
    assert f.parse(json.dumps(rows).encode()) is None


def test_lands_once_and_a_rerun_skips(tmp_path: Path) -> None:
    landing, table = Landing(tmp_path / "fii_dii"), tmp_path / "table.jsonl"
    serve = Serve(_payload())
    assert (
        f.capture(_fetcher(serve), landing, today=date(2026, 8, 17), derived=table) == "downloaded"
    )
    assert f.capture(_fetcher(serve), landing, today=date(2026, 8, 18), derived=table) == "skipped"
    entries = [e for (_, seg), e in landing.entries().items() if seg == "cash"]
    assert len(entries) == 1 and entries[0].trade_date == "2026-08-17"
    assert len(f.rows(table)) == 1


def test_a_pruned_file_still_counts_as_held(tmp_path: Path) -> None:
    """Files move to B2 and are deleted locally; the manifest is what says held."""
    landing, table = Landing(tmp_path / "fii_dii"), tmp_path / "table.jsonl"
    f.capture(_fetcher(Serve(_payload())), landing, today=date(2026, 8, 17), derived=table)
    landed = tmp_path / "fii_dii" / next(iter(landing.entries().values())).path
    landed.chmod(0o644)
    landed.unlink()
    again = Landing(tmp_path / "fii_dii")
    assert (
        f.capture(_fetcher(Serve(_payload())), again, today=date(2026, 8, 17), derived=table)
        == "skipped"
    )
    assert len((tmp_path / "fii_dii" / "manifest.jsonl").read_text().splitlines()) == 1


def test_a_future_date_and_a_bad_page_are_not_landed(tmp_path: Path) -> None:
    landing, table = Landing(tmp_path / "fii_dii"), tmp_path / "table.jsonl"
    assert (
        f.capture(_fetcher(Serve(_payload())), landing, today=date(2026, 8, 16), derived=table)
        == "malformed"
    )
    assert (
        f.capture(_fetcher(Serve(b"<html/>")), landing, today=date(2026, 8, 17), derived=table)
        == "malformed"
    )
    assert (
        f.capture(_fetcher(Serve(b"", 403)), landing, today=date(2026, 8, 17), derived=table)
        == "failed"
    )
    assert landing.entries() == {} and not table.exists()


def test_rows_never_return_what_was_not_yet_known(tmp_path: Path) -> None:
    table = tmp_path / "table.jsonl"
    day = f.parse(_payload())
    assert day is not None
    f.append(day, "2026-08-17T13:40:00+00:00", table)
    assert f.rows(table, as_of=datetime(2026, 8, 17, 13, 0, tzinfo=UTC)) == []
    assert len(f.rows(table, as_of=datetime(2026, 8, 17, 14, 0, tzinfo=UTC))) == 1
    with pytest.raises(ValueError, match="time zone"):
        f.rows(table, as_of=datetime(2026, 8, 17, 14, 0))  # noqa: DTZ001


def test_rebuild_is_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "landing"
    landing, table = Landing(root / "fii_dii"), tmp_path / "table.jsonl"
    for text, today in (("17-Aug-2026", 17), ("18-Aug-2026", 18)):
        f.capture(
            _fetcher(Serve(_payload(day=text))), landing, today=date(2026, 8, today), derived=table
        )
    first = table.read_bytes()

    def read(relative: str) -> bytes:
        return (root / relative).read_bytes()

    assert f.rebuild(Landing(root / "fii_dii"), read, table) == 2
    assert table.read_bytes() == first


def test_streak_counts_sessions_of_the_same_sign() -> None:
    assert f.streak([1, -2, -3, -4]) == -3
    assert f.streak([-1, 2, 3]) == 2
    assert f.streak([5, 0]) == 0
    assert f.streak([]) == 0


def test_summary_totals_the_week_and_month() -> None:
    held = [
        {
            "day": d,
            "knowledge_time": f"{d}T14:00:00+00:00",
            "fii_buy": 100.0,
            "fii_sell": 100.0 - net,
            "fii_net": net,
            "dii_buy": 50.0,
            "dii_sell": 40.0,
            "dii_net": 10.0,
        }
        for d, net in (
            ("2026-07-31", 500.0),
            ("2026-08-03", -100.0),
            ("2026-08-04", -200.0),
            ("2026-08-05", 50.0),
            ("2026-08-06", -300.0),
            ("2026-08-07", -400.0),
        )
    ]
    out = f.summary(held)
    assert out["available"] and out["as_of"] == "2026-08-07"
    assert out["fii"]["net_5d"] == -950.0
    assert out["fii"]["net_month"] == -950.0
    assert out["fii"]["streak"] == -2
    assert out["dii"]["streak"] == 6
    assert [m["month"] for m in out["months"]] == ["2026-07", "2026-08"]
    assert out["months"][1]["days"] == 5


def test_summary_says_why_when_empty() -> None:
    out = f.summary([])
    assert not out["available"] and "make fii-dii" in out["reason"]


def test_route_answers_from_the_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.api import fii_dii_routes

    table = tmp_path / "table.jsonl"
    day = f.parse(_payload())
    assert day is not None
    f.append(day, "2026-08-17T13:40:00+00:00", table)
    monkeypatch.setattr(f.rows, "__defaults__", (table,))
    body = fii_dii_routes.fii_dii()
    assert body["available"] and body["fii"]["net"] == -2535.10 and body["dii"]["streak"] == 1


def test_coverage_and_the_feed_know_the_dataset() -> None:
    from eulerlab.ingest import coverage, daily_feed, india_live
    from eulerlab.quality.contract import load_register

    assert "FII/DII cash flows" in {name for name, _ in daily_feed.STEPS}
    assert "FII/DII cash flows" in india_live.INDIA_STEPS
    assert coverage.STEPS_FOR["FII/DII cash flows"] == ("FII/DII cash flows",)
    names = load_register().by_name()
    assert names["FII/DII cash flows"].tree == f.TREE
    assert names["FII/DII cash table"].derived == str(f.DERIVED)
