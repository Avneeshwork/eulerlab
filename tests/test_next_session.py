"""The next-session forecast: features without look-ahead, the models, scoring and the log (ADR-133)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from eulerlab.agents import brief_content
from eulerlab.forecast import next_session as ns

S = ns.setup()


def _bars(n: int = 700, seed: int = 7) -> list[ns.Bar]:
    """A seeded random walk on weekdays, with a VIX that tracks recent ranges."""
    rng = np.random.default_rng(seed)
    out: list[ns.Bar] = []
    day, close, vix = date(2020, 1, 1), 10000.0, 15.0
    while len(out) < n:
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        sigma = vix / 100 / math.sqrt(252)
        opened = close * math.exp(rng.normal(0.0003, sigma / 3))
        shut = opened * math.exp(rng.normal(0, sigma))
        high = max(opened, shut) * math.exp(abs(rng.normal(0, sigma / 2)))
        low = min(opened, shut) * math.exp(-abs(rng.normal(0, sigma / 2)))
        vix = float(np.clip(vix * math.exp(rng.normal(0, 0.05)), 9, 40))
        out.append(ns.Bar(day, opened, high, low, shut, vix))
        close = shut
    return out


def _write_index(path: Path, history: list[ns.Bar]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for b in history:
            row = {
                "d": b.day.isoformat(),
                "event_time": f"{b.day}T15:30:00+05:30",
                "knowledge_time": f"{b.day}T20:00:00+05:30",
                "indices": {
                    "Nifty 50": {"o": b.open, "h": b.high, "l": b.low, "c": b.close},
                    "India VIX": {"c": b.vix},
                },
            }
            handle.write(json.dumps(row) + "\n")


def test_features_use_only_what_was_known_at_the_close() -> None:
    history = _bars(400)
    rows = ns.table(history, {}, {})
    changed = [*history[:-1], replace(history[-1], close=history[-1].close * 1.2)]
    again = ns.table(changed, {}, {})
    # Changing the last session moves only the row whose outcome it is, and its own row.
    assert [r.x for r in rows[:-1]] == [r.x for r in again[:-1]]
    assert [r.rx for r in rows[:-1]] == [r.rx for r in again[:-1]]
    assert rows[-2].ret != again[-2].ret
    assert rows[-1].ret is None and rows[-1].target is None


def test_fii_week_needs_the_day_itself_and_five_sessions() -> None:
    days = [date(2026, 10, d) for d in (26, 27, 28, 29, 30)]
    fii = dict.fromkeys(days, 100.0)
    assert ns.fii_week(fii, days, date(2026, 10, 30)) == 500.0
    assert ns.fii_week(fii, days, date(2026, 10, 29)) is None  # only four before it
    assert ns.fii_week(fii, days, date(2026, 10, 31)) is None  # not captured that day


def test_us_session_is_the_one_that_closed_between_the_two_india_sessions() -> None:
    spy = {date(2026, 11, 2): 100.0, date(2026, 11, 3): 101.0, date(2026, 11, 5): 102.0}
    days = sorted(spy)
    # India closed 11-03, next opens 11-04: the US session of 11-03 closed in between.
    assert ns.us_session(spy, days, date(2026, 11, 3), date(2026, 11, 4)) == pytest.approx(
        math.log(1.01)
    )
    # India 11-04 to 11-05: the US held no session in between (the next closes after 11-05 opens).
    assert ns.us_session(spy, days, date(2026, 11, 4), date(2026, 11, 5)) == 0.0
    assert ns.us_session(spy, days, date(2026, 11, 5), date(2026, 11, 6)) == pytest.approx(
        math.log(102 / 101)
    )
    # Past the US data's end: unknown, not zero.
    assert ns.us_session(spy, days, date(2026, 11, 6), date(2026, 11, 9)) is None


def test_a_huge_penalty_leaves_the_base_rate() -> None:
    rng = np.random.default_rng(1)
    xs = [{"a": float(v)} for v in rng.normal(size=400)]
    y = np.array([float(x["a"] > 0) for x in xs])
    w = np.ones(400)
    strong = ns.fit_logit(["a"], xs, y, w, ridge=0.1)
    flat = ns.fit_logit(["a"], xs, y, w, ridge=1e9)
    assert strong.beta[1] > 2
    assert abs(flat.beta[1]) < 1e-4
    assert 1 / (1 + math.exp(-flat.beta[0])) == pytest.approx(y.mean(), abs=1e-3)


def test_the_forecast_is_deterministic_and_its_band_holds_the_last_close() -> None:
    history = _bars()
    rows = ns.table(history, {}, {}, next_target=history[-1].day + timedelta(days=3))
    now = datetime(2030, 1, 1, tzinfo=UTC)
    a = ns.predict(ns.fit(rows, S), rows[-1], history[-1].vix, now)
    b = ns.predict(ns.fit(rows, S), rows[-1], history[-1].vix, now)
    assert asdict(a) == asdict(b)
    assert a.band_low < a.last_close < a.band_high
    assert 0 < a.p_up < 1 and 0 < a.p_gap_up < 1
    assert a.range_pct > 0 and a.vix_range_pct is not None
    assert not a.second_stage  # no flows or US data held


def test_the_walk_forward_check_fits_only_on_sessions_before_each_forecast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _bars(520)
    rows = ns.table(history, {}, {})
    real = ns.fit
    seen: list[date] = []

    def watched(fitted: list[ns.Row], s: ns.Setup) -> ns.Model:
        seen.append(max(r.target for r in fitted if r.target))
        return real(fitted, s)

    monkeypatch.setattr(ns, "fit", watched)
    small = S.model_copy(update={"check_sessions": 100, "refit_every": 25})
    card = ns.check(rows, small)
    assert card.n == 100 and len(seen) == 4
    done = [r for r in rows if r.ret is not None]
    starts = [done[-100 + 25 * k].day for k in range(4)]
    assert all(s <= d for s, d in zip(seen, starts, strict=True))
    assert card.in_band is not None and 0.6 < card.in_band < 0.95


def test_the_log_keeps_forecasts_made_before_the_open_and_scores_the_last_one(
    tmp_path: Path,
) -> None:
    history = _bars(400)
    target = history[-1]
    rows = ns.table(history[:-1], {}, {}, next_target=target.day)
    model = ns.fit(rows, S)
    log = tmp_path / "log.jsonl"
    evening = datetime.combine(history[-2].day, datetime.min.time(), ns.IST) + timedelta(hours=20)
    morning = datetime.combine(target.day, datetime.min.time(), ns.IST) + timedelta(hours=8)
    late = datetime.combine(target.day, datetime.min.time(), ns.IST) + timedelta(hours=10)
    first = ns.predict(model, rows[-1], 15.0, evening)
    assert ns.record(first, log)
    assert not ns.record(replace(first, made_at=evening.isoformat()), log)  # same forecast
    second = ns.predict(model, rows[-1], 18.0, morning)
    assert ns.record(second, log)
    assert not ns.record(ns.predict(model, rows[-1], 20.0, late), log)  # after the open
    held = ns.logged(log)
    assert len(held) == 2
    assert {"event_time", "knowledge_time"} <= held[0].keys()
    scored = ns.live_scores(history, log)
    assert len(scored) == 1
    assert scored[0]["forecast"]["vix_range_pct"] == second.vix_range_pct
    assert scored[0]["close"] == target.close
    assert scored[0]["up"] == (target.close > history[-2].close)


def test_trust_falls_back_to_the_base_rate_when_the_model_trails_it() -> None:
    walked = ns.Card(n=500, brier_up=0.26, brier_up_base=0.25, brier_gap=0.24, brier_gap_base=0.25)
    ok, why = ns.trust(ns.Card(), walked, S, "up")
    assert not ok and "base rate is shown" in why and "walk-forward" in why
    ok, why = ns.trust(ns.Card(), walked, S, "gap")
    assert ok and "skill +4.0%" in why
    live = ns.Card(n=S.min_live, brier_up=0.20, brier_up_base=0.25)
    ok, why = ns.trust(live, walked, S, "up")
    assert ok and "live" in why


def test_build_forecasts_logs_and_reads_like_a_brief(tmp_path: Path) -> None:
    history = _bars(700)
    _write_index(ns.INDEX_HISTORY, history)
    now = datetime.combine(history[-1].day, datetime.min.time(), ns.IST) + timedelta(hours=21)
    small = S.model_copy(update={"check_sessions": 60})
    out = ns.build(now=now, s=small)
    assert out["available"] and not out["late"]
    f = out["forecast"]
    assert (
        f["target"]
        == (
            history[-1].day + timedelta(days=3 if history[-1].day.weekday() == 4 else 1)
        ).isoformat()
    )
    assert len(ns.logged()) == 1
    assert out["story"] and out["story"][0].startswith("Nifty 50 closed at")
    text = "\n".join(brief_content.forecast_lines(out))
    assert "WHAT CAN HAPPEN NEXT SESSION" in text and "SCENARIOS FOR THE NEXT SESSION" in text
    assert "- Reason: " in text or "- The close: " in text
    assert "Walk-forward check" in text and "Live: no session scored yet" in text
    # A knowledge_time after `now` is not read.
    assert ns.bars(ns.INDEX_HISTORY, as_of=now - timedelta(days=1))[-1].day < history[-1].day


def test_the_review_says_what_the_last_forecast_got_right_and_wrong() -> None:
    f: dict[str, Any] = {
        "target": "2026-11-04",
        "made_at": "2026-11-04T03:00:00+00:00",
        "band_low": 23500.0,
        "band_high": 24100.0,
        "range_pct": 1.1,
        "vix_range_pct": 1.6,
        "p_up": 0.56,
        "base_up": 0.52,
        "p_gap_up": 0.64,
        "last_close": 23810.0,
    }
    last = ns.outcome(f | {"base_gap_up": 0.6}, 23900.0, 24200.0, 1.5)
    last["forecast"] = f
    lines = brief_content.forecast_review({"available": True, "last_scored": last}, "2026-11-04")
    assert "The close was above the band; the odds leaned higher, which was right." in lines[1]
    assert lines[2].startswith("The range forecast was too narrow by 36%")
    assert brief_content.forecast_review({"available": True, "last_scored": last}, "2026-11-05")[
        0
    ].startswith("Today's forecast is scored once")


def test_an_expired_option_chain_is_left_out() -> None:
    from eulerlab.agents import trader_read

    assert trader_read.expired({"expiry": "2026-11-03"}, "2026-11-03")
    assert not trader_read.expired({"expiry": "2026-11-10"}, "2026-11-03")
    assert not trader_read.expired({}, "2026-11-03")
