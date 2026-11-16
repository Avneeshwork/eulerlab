"""The experiment store and the firewall's numbers (ADR-172)."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.research import experiments
from eulerlab.validation import firewall

REPO = Path(__file__).parents[1]
NOW = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)  # the constitution is read from config/


def _days(first: date, n: int) -> list[date]:
    out: list[date] = []
    day = first
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _series(seed: int, days: list[date], drift: float = 0.0) -> dict[date, float]:
    rng = random.Random(seed)
    return {d: rng.gauss(drift, 0.01) for d in days}


def _record(tmp_path: Path, fingerprint: str, daily: dict[date, float], **kw: object) -> str:
    return experiments.record(
        purpose=kw.pop("purpose", "screen"),  # type: ignore[arg-type]
        fingerprint=fingerprint,
        first=min(daily),
        end=max(daily),
        metrics={"net_sharpe": 1.0},
        daily=daily,
        now=NOW,
        path=tmp_path / "experiments.jsonl",
        returns_root=tmp_path / "returns",
        **kw,  # type: ignore[arg-type]
    )


def test_a_screen_is_kept_with_its_daily_returns(tmp_path: Path) -> None:
    daily = _series(1, _days(date(2022, 1, 3), 100))
    made = _record(tmp_path, "abc", daily, hypothesis="H-0999", family="intraday:gap")
    (row,) = experiments.rows(tmp_path / "experiments.jsonl")
    assert row["id"] == made and row["purpose"] == "screen" and row["family"] == "intraday:gap"
    back = experiments.returns_of(row, tmp_path / "returns")
    assert back == pytest.approx(daily)


def test_the_same_series_is_stored_once_and_the_file_only_grows(tmp_path: Path) -> None:
    daily = _series(1, _days(date(2022, 1, 3), 100))
    _record(tmp_path, "abc", daily)
    first = (tmp_path / "experiments.jsonl").read_text()
    _record(tmp_path, "abc", daily, purpose="gate")
    assert (tmp_path / "experiments.jsonl").read_text().startswith(first)
    assert len(list((tmp_path / "returns").iterdir())) == 1
    assert experiments.counts(tmp_path / "experiments.jsonl") == {
        "screen": 1,
        "gate": 1,
        "rules": 1,
    }


def test_a_screen_that_reads_2026_is_refused(tmp_path: Path) -> None:
    daily = _series(1, _days(date(2025, 12, 1), 40))  # runs into January 2026
    with pytest.raises(experiments.SealedPeriod, match="forward test"):
        _record(tmp_path, "abc", daily)
    assert not (tmp_path / "experiments.jsonl").exists()
    _record(tmp_path, "abc", daily, purpose="forward")  # scoring the forward test may


def test_coverage_counts_distinct_rules_per_family(tmp_path: Path) -> None:
    days = _days(date(2022, 1, 3), 100)
    _record(tmp_path, "a", _series(1, days), family="intraday:gap")
    _record(tmp_path, "a", _series(1, days), family="intraday:gap")
    _record(tmp_path, "b", _series(2, days), family="intraday:gap")
    _record(tmp_path, "c", _series(3, days), family="swing:ret")
    assert experiments.coverage(tmp_path / "experiments.jsonl") == {
        "intraday:gap": 2,
        "swing:ret": 1,
    }
    series = experiments.universe(tmp_path / "experiments.jsonl", tmp_path / "returns", skip=["a"])
    assert len(series) == 2


# --- the firewall ---------------------------------------------------------------------------

LONG = _days(date(2021, 1, 4), 1200)  # into 2025: both periods have sessions


def test_copies_of_one_rule_are_one_family() -> None:
    base = _series(1, LONG, drift=0.001)
    copies = [{d: v * (1 + 0.01 * k) for d, v in base.items()} for k in range(1, 6)]
    others = [_series(s, LONG) for s in (2, 3, 4)]
    found = firewall.assess(base, "abc", [*copies, *others])
    assert found.rules_tried == 9
    assert found.families == 4  # the rule with its five copies, and three more


def test_more_families_tried_lowers_the_deflated_sharpe() -> None:
    rule = _series(1, LONG, drift=0.0008)
    few = firewall.assess(rule, "abc", [_series(s, LONG) for s in range(2, 5)])
    many = firewall.assess(rule, "abc", [_series(s, LONG) for s in range(2, 40)])
    assert few.deflated_sharpe is not None and many.deflated_sharpe is not None
    assert many.families is not None and few.families is not None
    assert many.families > few.families
    assert many.deflated_sharpe <= few.deflated_sharpe


def test_a_rule_that_dies_after_2023_does_not_hold() -> None:
    alive = _series(1, LONG, drift=0.002)
    dead = {d: (v if d <= date(2023, 12, 31) else -abs(v)) for d, v in alive.items()}
    assert firewall.holds(alive, "abc")[2] is True
    base, days, kept = firewall.holds(dead, "abc")
    assert base is not None and base > 0 and days >= firewall.MIN_DAYS and kept is False


def test_too_short_a_selection_period_gives_no_answer() -> None:
    short = _series(1, _days(date(2022, 1, 3), 300), drift=0.002)  # ends early 2023
    assert firewall.holds(short, "abc")[2] is None


def test_the_same_rule_always_gets_the_same_answer() -> None:
    rule = _series(1, LONG, drift=0.001)
    others = [_series(s, LONG) for s in range(2, 8)]
    assert firewall.assess(rule, "abc", others) == firewall.assess(rule, "abc", others)


# --- a search ranks on discovery data; the selection period answers once (#152) --------


def test_a_search_that_reads_the_selection_period_is_refused(tmp_path: Path) -> None:
    daily = _series(1, _days(date(2023, 11, 1), 60))  # runs into 2024
    for purpose in ("screen", "sweep"):
        with pytest.raises(experiments.SealedPeriod, match="discovery end"):
            _record(tmp_path, "abc", daily, purpose=purpose)
    assert not (tmp_path / "experiments.jsonl").exists()
    _record(tmp_path, "abc", daily, purpose="gate")  # the gate reads to backtest_end
    _record(tmp_path, "abc", daily, purpose="selection")


def test_a_look_keeps_one_bit_and_no_selection_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import paths

    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    alive = _series(1, LONG, drift=0.002)
    found = {d: v for d, v in alive.items() if d <= date(2023, 12, 31)}
    dead = {d: (v if d <= date(2023, 12, 31) else -abs(v)) for d, v in alive.items()}
    # Only the selection days of the full run are read: its discovery days are ignored.
    days, kept = firewall.look(
        found,
        {d: -1.0 if d.year < 2024 else v for d, v in alive.items()},
        "abc",
        first=min(found),
        asked_by="test",
        now=NOW,
    )
    assert kept is True and days >= firewall.MIN_DAYS
    assert firewall.look(found, dead, "abc", first=min(found), asked_by="test", now=NOW)[1] is False
    looks = experiments.rows(purpose="selection")
    assert len(looks) == 2 and all(r["returns"] is None for r in looks)
    assert looks[0]["metrics"] == {"holds_on_selection": True, "selection_days": days}
