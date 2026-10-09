"""The Instruments data pipeline: one run at a time, nothing twice, coverage visible.

T-4032. The button fetched but never rebuilt the panel or the paper books, it
could run alongside `make daily` and append the same day twice, and nothing
showed what was missing.
"""

from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from eulerlab.features.panel import build, cached_days
from eulerlab.ingest import coverage, daily_feed, filelock
from eulerlab.ingest.manifest import latest_date

# --- locks ----------------------------------------------------------------------


def test_a_held_feed_lock_refuses_a_second_run(tmp_path: Path) -> None:
    with filelock.exclusive("feed", wait=False, what="make daily", directory=tmp_path):
        held = filelock.holder("feed", directory=tmp_path)
        assert held is not None and held["what"] == "make daily"
        with (
            pytest.raises(filelock.Busy),
            filelock.exclusive("feed", wait=False, directory=tmp_path),
        ):
            pass
    assert filelock.holder("feed", directory=tmp_path) is None


def test_the_feed_refuses_while_make_daily_holds_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(daily_feed, "STEPS", (("never runs", lambda: "ran"),))
    with filelock.exclusive("feed", wait=False, what="make daily"), pytest.raises(filelock.Busy):
        daily_feed.refresh(sync=False)


def test_the_cli_wrapper_exits_75_when_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with filelock.exclusive("feed", wait=False):
        assert filelock.main(["feed", "--", "true"]) == 75
    assert filelock.main(["feed", "--", "true"]) == 0


# --- no duplicate days ---------------------------------------------------------

UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
    "{day},{day},CM,NSE,STK,1,INE000A01001,ACME,EQ,,,,,ACME,100,110,95,105,"
    "105,99,,105,,,5000,525000,200,F1,1,,,,,\n"
)


def _land(root: Path, days: list[str]) -> Path:
    lines = []
    for day in days:
        key = f"cm/{day[:4]}/{day[5:7]}/{day}_udiff.zip"
        (root / key).parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("bhav.csv", UDIFF.format(day=day))
        (root / key).write_bytes(buf.getvalue())
        lines.append(json.dumps({"segment": "cm", "trade_date": day, "path": key}))
    manifest = root / "manifest.jsonl"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def test_two_builders_at_once_write_each_day_once(tmp_path: Path) -> None:
    days = ["2026-10-06", "2026-10-07", "2026-10-08"]
    manifest = _land(tmp_path / "nse", days)
    panel = tmp_path / "panel.jsonl"

    def go() -> None:
        build(start="2026-10-01", end="2026-10-31", manifest=manifest, path=panel)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    written = [json.loads(x)["d"] for x in panel.read_text().splitlines()]
    assert sorted(written) == days, "each day exactly once"
    assert cached_days(panel) == set(days)


# --- coverage --------------------------------------------------------------------

AFTER_CLOSE = datetime(2026, 10, 8, 14, 0, tzinfo=UTC)  # 19:30 IST, a Thursday
BEFORE_FILES = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)  # 15:30 IST


def test_nse_expects_today_only_after_1900_ist() -> None:
    assert coverage.expected_nse(AFTER_CLOSE, frozenset()) == date(2026, 10, 8)
    assert coverage.expected_nse(BEFORE_FILES, frozenset()) == date(2026, 10, 7)


def test_weekends_and_known_closures_are_not_sessions() -> None:
    monday_evening = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
    closed = frozenset({date(2026, 10, 2)})
    expected = coverage.expected_nse(monday_evening, closed)
    assert expected == date(2026, 10, 5)
    # Thursday 1 Oct -> Monday 5 Oct, with Friday 2 Oct closed: one session.
    assert coverage.sessions_behind(date(2026, 10, 1), expected, "nse", closed) == 1


def test_judge_grades_by_sessions_behind() -> None:
    def status(last: str) -> str:
        return coverage.judge(
            group="g", name="n", last=last, cadence="nse", now=AFTER_CLOSE, closed=frozenset()
        ).status

    assert status("2026-10-08") == "ok"
    assert status("2026-10-07") == "behind"
    assert status("2026-10-05") == "stale"
    assert status("") == "missing"


def test_the_last_line_is_read_from_the_end(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    path.write_text(
        "".join(json.dumps({"d": f"2026-01-{i % 28 + 1:02d}"}) + "\n" for i in range(50_000))
        + json.dumps({"d": "2026-10-08"})
        + "\n"
    )
    assert coverage.last_day_jsonl(path) == "2026-10-08"
    assert coverage.last_day_jsonl(tmp_path / "absent.jsonl") == ""


def test_the_census_dates_by_key_not_by_file_name() -> None:
    keys = [
        "crypto/ZRO/ZROUSDT-1m-2026-10-07.jsonl.gz",
        "crypto/BTC/BTCUSDT-1m-2026-10-08.jsonl.gz",
    ]
    assert latest_date(keys) == "2026-10-08"
    assert (
        latest_date(["us/bars/AAPL/2026-09.jsonl.gz", "us/bars/AAPL/2026-10.jsonl.gz"]) == "2026-10"
    )
    assert latest_date(["mf/history/119551.jsonl.gz"]) == ""


# --- the button and make daily run the same thing --------------------------------


def test_every_make_daily_step_is_in_the_button_or_named_as_terminal_only() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\ndaily-run:\n", 1)[1].split("\n\n", 1)[0]
    ran = set(re.findall(r"-m (eulerlab[\w.]+)", recipe))
    ran |= set(re.findall(r"\$\(MAKE\)(?: --no-print-directory)? ([\w-]+)", recipe))
    ran |= {"eulerlab.ingest.alpaca"} if "from eulerlab.ingest import alpaca" in recipe else set()
    covered = set(daily_feed.STEP_MODULES.values()) | set(daily_feed.TERMINAL_ONLY)
    # build-us-panel is how make names the US panel step; the sync is named by target.
    assert ran - covered == set(), f"make daily runs these, the button does not: {ran - covered}"
    assert {name for name, _ in daily_feed.STEPS} == set(daily_feed.STEP_MODULES)


def test_the_panel_and_paper_books_come_straight_after_the_nse_files() -> None:
    names = [name for name, _ in daily_feed.STEPS]
    assert names.index("price panel") > names.index("NSE end-of-day")
    assert names.index("paper books") == names.index("price panel") + 2
    assert names.index("paper books") < names.index("mutual fund NAVs")


# --- step reports ----------------------------------------------------------------


def test_fetch_counts_reads_both_report_shapes() -> None:
    eod = "  downloaded       1\n  skipped          9  (already landed)\n"
    files = "  done: {'downloaded': 5, 'absent': 1}\n  done: {'skipped': 6}\n"
    assert daily_feed.fetch_counts(eod) == "downloaded 1, already held 9"
    assert daily_feed.fetch_counts(files) == "downloaded 5, already held 6"
    assert daily_feed.fetch_counts("nothing to count") == ""


def test_a_non_zero_exit_fails_the_step() -> None:
    def failing() -> int:
        print("delivery: 3 failed")
        return 1

    with pytest.raises(RuntimeError, match="exit 1: delivery: 3 failed"):
        daily_feed._captured(failing)
    assert "kept" in daily_feed._captured(lambda: print("kept") or 0)


# --- the US panel re-reads only recent months ------------------------------------


def test_the_us_panel_rereads_only_the_last_two_months(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.features import us_panel
    from eulerlab.ingest import landing_reader

    path = tmp_path / "us_panel.jsonl"
    old = {"d": "2025-11-03", "s": "OLD", "c": 10.0, "v": 1.0, "o": 10.0, "h": 10.0, "l": 10.0}
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    today = datetime.now(UTC).date()
    month = today.strftime("%Y-%m")
    listed = [f"bars/NEW/{month}.jsonl.gz", "bars/OLD/2025-11.jsonl.gz"]
    read: list[str] = []

    def fake_read(relative: str) -> bytes:
        import gzip

        read.append(relative)
        row = {"symbol": "NEW", "event_time": today.isoformat(), "close": 5.0}
        return gzip.compress((json.dumps(row) + "\n").encode())

    monkeypatch.setattr(landing_reader, "available", lambda *a, **k: listed)
    monkeypatch.setattr(landing_reader, "read", fake_read)
    rows, symbols = us_panel.build(path=path)

    assert read == [f"bars/NEW/{month}.jsonl.gz"], "the older month is kept, not re-read"
    assert (rows, symbols) == (2, 2)


# --- the API -------------------------------------------------------------------


def test_the_coverage_endpoint_lists_every_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.api import server

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coverage, "LANDING", tmp_path / "landing")
    monkeypatch.setattr(coverage, "DERIVED", tmp_path / "derived")
    monkeypatch.setattr(coverage, "DEPLOYMENTS", tmp_path / "deployments")
    payload = server.data_coverage()

    names = {row["name"] for row in payload["rows"]}
    assert {"Cash bhavcopy", "Price panel", "Nifty options", "US daily panel"} <= names
    assert payload["summary"]["missing"] >= 4, "an empty machine says missing, not ok"
    assert payload["busy"] is None


def test_the_button_refuses_while_another_run_holds_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.api import server

    monkeypatch.chdir(tmp_path)
    with filelock.exclusive("feed", wait=False, what="make daily-run"):
        answer = server.data_feed()
    assert answer["ok"] is False
    assert "make daily-run" in answer["error"]


def test_delete_and_mirror_refuse_while_an_update_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.api import server
    from eulerlab.api.requests import PruneRequest

    monkeypatch.chdir(tmp_path)
    with filelock.exclusive("feed", wait=False, what="Instruments → Update all data"):
        pruned = server.data_prune(PruneRequest(dry_run=False))
        mirrored = server.data_sync()
    assert pruned["ok"] is False and "Update all data" in pruned["error"]
    assert mirrored["ok"] is False and "Update all data" in mirrored["error"]


def test_delete_defaults_to_a_dry_run() -> None:
    from eulerlab.api.requests import PruneRequest

    assert PruneRequest().dry_run is True


# --- one dataset's button --------------------------------------------------------


def test_every_dataset_button_runs_real_feed_steps_in_order() -> None:
    order = [name for name, _ in daily_feed.STEPS]
    for dataset, steps in {**coverage.STEPS_FOR, "paper": coverage.PAPER_STEPS}.items():
        assert set(steps) <= set(order), f"{dataset} names a step that does not exist"
        positions = [order.index(s) for s in steps]
        assert positions == sorted(positions), f"{dataset}: the fetch must come before the build"


def test_one_dataset_runs_only_its_steps_and_skips_the_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []

    def step(name: str) -> Callable[[], str]:
        def work() -> str:
            ran.append(name)
            return name

        return work

    monkeypatch.setattr(daily_feed, "STEPS", tuple((n, step(n)) for n in ("a", "b", "c")))
    monkeypatch.setattr(daily_feed, "_mirror", lambda **k: pytest.fail("mirrored"))
    run = daily_feed.refresh(only=["c", "a"], sync=False)
    assert ran == ["a", "c"], "STEPS order, not request order"
    assert run.summary == "all 2 sources updated"


def test_the_api_refuses_a_step_that_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.api import server
    from eulerlab.api.requests import FeedRequest

    monkeypatch.chdir(tmp_path)
    answer = server.data_feed(FeedRequest(only=["price panel", "rm -rf"], mirror=False))
    assert answer["ok"] is False and "rm -rf" in answer["error"]
