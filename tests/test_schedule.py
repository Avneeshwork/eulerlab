"""The scheduled jobs: what launchd is told, and when the gap signal stays quiet."""

from __future__ import annotations

import plistlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab import notify
from eulerlab.research import gap_signal
from tools import schedule_daily

REPO = Path("/repo")


def _job(name: str) -> dict[str, object]:
    job = schedule_daily.JOBS[name]
    text = schedule_daily.plist(REPO, hour=job.hour, minute=job.minute, job=job)
    loaded: dict[str, object] = plistlib.loads(text.encode())  # must be well-formed XML
    return loaded


def test_the_daily_job_is_what_it_was() -> None:
    job = _job("daily")
    assert job["Label"] == "com.eulerlab.daily"
    assert job["ProgramArguments"] == ["/bin/zsh", "-lc", "/repo/tools/daily_guard.sh"]
    assert job["StartCalendarInterval"] == {"Hour": 19, "Minute": 30}
    assert job["RunAtLoad"] is False


def test_the_gap_signal_runs_at_1520_on_weekdays_only() -> None:
    job = _job("gap-signal")
    assert job["Label"] == "com.eulerlab.gapsignal"
    # The `&&` survives the XML: launchd gets the command as written.
    assert job["ProgramArguments"] == [
        "/bin/zsh",
        "-lc",
        "cd /repo && make gap-signal SCHEDULED=1",
    ]
    assert job["StartCalendarInterval"] == [
        {"Weekday": day, "Hour": 15, "Minute": 20} for day in (1, 2, 3, 4, 5)
    ]
    assert job["RunAtLoad"] is False
    assert str(job["StandardOutPath"]).endswith("data/logs/gap_signal.log")


@pytest.mark.parametrize(
    ("when", "sends"),
    [
        ("2026-10-12T09:50:00", True),  # Monday 15:20 IST
        ("2026-10-12T09:36:00", True),  # 15:06, a little early: still reports
        ("2026-10-12T10:14:00", True),  # 15:44, a little late: still reports
        ("2026-10-12T15:30:00", False),  # 21:00, a run caught up after sleep
        ("2026-10-12T03:30:00", False),  # 09:00
        ("2026-10-10T09:50:00", False),  # Saturday
        ("2026-10-11T09:50:00", False),  # Sunday
    ],
)
def test_an_unattended_run_sends_only_near_the_close_on_a_weekday(
    when: str, sends: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("eulerlab.ingest.coverage.nse_closures", lambda *a, **k: frozenset())
    now = datetime.fromisoformat(when).replace(tzinfo=UTC)
    assert (gap_signal.out_of_session(now) == "") is sends


def test_an_nse_holiday_is_quiet_and_a_scheduled_run_then_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 10, 12, 9, 50, tzinfo=UTC)
    monkeypatch.setattr(
        "eulerlab.ingest.coverage.nse_closures", lambda *a, **k: frozenset({now.date()})
    )
    assert gap_signal.out_of_session(now) == "NSE holiday"

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("a quiet run reached Kite or Telegram")

    monkeypatch.setattr(gap_signal, "read_live", forbidden)
    monkeypatch.setattr(notify, "send", forbidden)
    monkeypatch.setattr(gap_signal, "out_of_session", lambda _now: "NSE holiday")
    assert gap_signal.main(["--scheduled"]) == 0
    assert "nothing sent (NSE holiday)" in capsys.readouterr().out
