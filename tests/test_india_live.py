"""ADR-079: Indian data from 15:31, minute bars standing in for a missing bhavcopy."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from eulerlab.ingest import india_live, provisional_daily
from eulerlab.ingest.backfill_minute import complete_days, last_complete_session
from eulerlab.ingest.kite_minute import Chunk

DAY = date(2026, 10, 26)  # a Monday


def _minutes(day: date, last: str = "15:29", base: float = 100.0) -> list[list[object]]:
    out: list[list[object]] = []
    t = datetime(day.year, day.month, day.day, 9, 15, tzinfo=UTC)
    i = 0
    while t.strftime("%H:%M") <= last:
        p = base + i
        out.append([f"{day}T{t:%H:%M}:00+0530", p, p + 0.5, p - 0.5, p + 0.25, 10])
        t += timedelta(minutes=1)
        i += 1
    return out


def _land(root: Path, symbol: str, candles: list[list[object]], start: date, end: date) -> None:
    folder = root / symbol
    folder.mkdir(parents=True, exist_ok=True)
    cols = list(zip(*candles, strict=True))
    table = pa.table(
        {
            "ts": pa.array([str(c) for c in cols[0]], pa.string()),
            "open": pa.array(cols[1], pa.float64()),
            "high": pa.array(cols[2], pa.float64()),
            "low": pa.array(cols[3], pa.float64()),
            "close": pa.array(cols[4], pa.float64()),
            "volume": pa.array(cols[5], pa.int64()),
        }
    )
    pq.write_table(table, folder / f"{start}_{end}.parquet")


def _manifest(path: Path, days: list[str]) -> Path:
    path.write_text("".join(json.dumps({"segment": "cm", "trade_date": d}) + "\n" for d in days))
    return path


# --- the bar ---------------------------------------------------------------------


def test_a_session_bar_is_open_first_high_max_low_min_close_last() -> None:
    rows = [
        dict(zip(("ts", "open", "high", "low", "close", "volume"), c, strict=True))
        for c in _minutes(DAY)
    ]
    bar = provisional_daily.session_bar("ABC", DAY, rows)
    assert bar is not None
    assert bar.minutes == 375
    assert bar.open == 100.0
    assert bar.high == 100.0 + 374 + 0.5
    assert bar.low == 99.5
    assert bar.close == 100.0 + 374 + 0.25
    assert bar.volume == 3750


def test_a_session_is_complete_at_1529_or_at_1514_for_the_closing_auction(tmp_path: Path) -> None:
    _land(tmp_path, "CASH", _minutes(DAY), DAY, DAY)
    _land(tmp_path, "FNO", _minutes(DAY, last="15:14"), DAY, DAY)
    _land(tmp_path, "LAGGING", _minutes(DAY, last="15:22"), DAY, DAY)
    found = provisional_daily.bars_for(DAY, tmp_path)
    assert [b.symbol for b in found.bars] == ["CASH", "FNO"]
    assert found.incomplete == ["LAGGING"]


def test_before_the_closing_auction_only_1529_completes_a_day(tmp_path: Path) -> None:
    july = date(2026, 7, 31)
    _land(tmp_path, "FNO", _minutes(july, last="15:14"), july, july)
    assert provisional_daily.bars_for(july, tmp_path).incomplete == ["FNO"]


# --- record: stand in, then retire -----------------------------------------------


def test_minute_bars_stand_in_until_the_bhavcopy_lands_and_stay_on_record(tmp_path: Path) -> None:
    root, store = tmp_path / "minute", tmp_path / "provisional.jsonl"
    manifest = _manifest(tmp_path / "manifest.jsonl", ["2026-10-23"])
    _land(root, "ABC", _minutes(DAY), DAY, DAY)
    t1 = datetime(2026, 10, 26, 10, 5, tzinfo=UTC)

    first = provisional_daily.record(DAY, path=store, root=root, manifest=manifest, now=t1)
    assert (first.state, first.symbols) == ("provisional", 1)
    again = provisional_daily.record(DAY, path=store, root=root, manifest=manifest, now=t1)
    assert again.state == "provisional"
    assert len(store.read_text().splitlines()) == 1, "an unchanged day is not appended twice"
    assert "2026-10-26/ABC" in provisional_daily.read(store, as_of=t1.isoformat())

    _manifest(manifest, ["2026-10-23", "2026-10-26"])
    t2 = datetime(2026, 10, 26, 13, 0, tzinfo=UTC)
    done = provisional_daily.record(DAY, path=store, root=root, manifest=manifest, now=t2)
    assert done.state == "official"
    assert provisional_daily.read(store, as_of=t2.isoformat()) == {}
    # Before the bhavcopy landed, the provisional bar is still what was known.
    assert "2026-10-26/ABC" in provisional_daily.read(store, as_of=t1.isoformat())


def test_no_minute_bars_and_no_bhavcopy_is_missing(tmp_path: Path) -> None:
    out = provisional_daily.record(
        DAY,
        path=tmp_path / "p.jsonl",
        root=tmp_path / "none",
        manifest=_manifest(tmp_path / "m.jsonl", []),
    )
    assert out.state == "missing"
    assert not (tmp_path / "p.jsonl").exists()


# --- the minute ingest does not land an unfinished today -------------------------


def test_minute_cut_off_is_one_minute_after_the_close() -> None:
    assert last_complete_session(datetime(2026, 10, 26, 10, 1, tzinfo=UTC)) == DAY
    assert last_complete_session(datetime(2026, 10, 26, 10, 0, tzinfo=UTC)) == DAY - timedelta(1)


def test_an_unfinished_today_is_cut_from_the_chunk() -> None:
    friday = date(2026, 10, 23)
    chunk = Chunk("ABC", 1, friday, DAY)
    candles = _minutes(friday) + _minutes(DAY, last="15:20")
    landing, kept = complete_days(chunk, candles, DAY)
    assert landing is not None and landing.end == DAY - timedelta(1)
    assert landing.key == chunk.key
    assert all(str(c[0]).startswith("2026-10-23") for c in kept)

    alone, nothing = complete_days(Chunk("ABC", 1, DAY, DAY), _minutes(DAY, "15:20"), DAY)
    assert (alone, nothing) == (None, [])

    fno, kept_fno = complete_days(Chunk("ABC", 1, DAY, DAY), _minutes(DAY, "15:14"), DAY)
    assert fno is not None and len(kept_fno) == 360

    whole, all_of_it = complete_days(Chunk("ABC", 1, DAY, DAY), _minutes(DAY), DAY)
    assert whole is not None and len(all_of_it) == 375


def test_an_older_short_day_is_landed_as_kite_serves_it() -> None:
    friday = date(2026, 10, 23)
    short = _minutes(friday, last="15:14")
    landing, kept = complete_days(Chunk("ABC", 1, friday, friday), short, DAY)
    assert landing is not None and kept == short


# --- the loop --------------------------------------------------------------------


class Clock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def test_the_loop_retries_until_the_bhavcopy_and_minute_bars_are_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(india_live, "trading_day", lambda now: DAY)
    clock = Clock(datetime(2026, 10, 26, 10, 1, tzinfo=UTC))
    states = iter(
        [
            india_live.Landed(bhavcopy=False, minute=False, token=True),
            india_live.Landed(bhavcopy=False, minute=True, token=True),
            india_live.Landed(bhavcopy=True, minute=True, token=True),
        ]
    )
    passes: list[datetime] = []

    def work() -> str:
        passes.append(clock.now())
        return "ok"

    code, line = india_live.run(
        now=clock.now, sleep=clock.sleep, work=work, check=lambda day: next(states)
    )
    assert code == 0 and "is in" in line
    assert [p.astimezone(india_live.IST).strftime("%H:%M") for p in passes] == [
        "15:31",
        "15:41",
        "15:51",
    ]


def test_without_a_kite_token_the_bhavcopy_alone_is_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(india_live, "trading_day", lambda now: DAY)
    clock = Clock(datetime(2026, 10, 26, 10, 1, tzinfo=UTC))
    code, _ = india_live.run(
        now=clock.now,
        sleep=clock.sleep,
        work=lambda: "ok",
        check=lambda day: india_live.Landed(bhavcopy=True, minute=False, token=False),
    )
    assert code == 0


def test_the_loop_gives_up_at_2100_and_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(india_live, "trading_day", lambda now: DAY)
    clock = Clock(datetime(2026, 10, 26, 15, 0, tzinfo=UTC))  # 20:30 IST
    code, line = india_live.run(
        now=clock.now,
        sleep=clock.sleep,
        work=lambda: "ok",
        check=lambda day: india_live.Landed(bhavcopy=False, minute=True, token=True),
    )
    assert code == 1
    assert "still missing" in line and "bhavcopy" in line


def test_no_session_means_no_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(india_live, "trading_day", lambda now: None)
    ran: list[int] = []

    def work() -> str:
        ran.append(1)
        return "ok"

    code, line = india_live.run(work=work)
    assert code == 0 and ran == [] and "no NSE session" in line


def test_india_live_is_scheduled_at_1531_on_weekdays() -> None:
    from tools import schedule_daily

    job = schedule_daily.JOBS["india-live"]
    assert (job.hour, job.minute, job.weekdays) == (15, 31, (1, 2, 3, 4, 5))
