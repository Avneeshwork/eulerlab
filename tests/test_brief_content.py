"""The market brief's content: what matters, coming up, the books, review, Telegram (ADR-105)."""

from __future__ import annotations

from datetime import date
from typing import Any

from eulerlab.agents import brief_content, trader_read
from eulerlab.agents.workers import market_brief

LV = trader_read.levels()


def _ctx() -> dict[str, Any]:
    return {
        "strip": {
            "indices": [
                {
                    "name": "Nifty 50",
                    "as_of": "2026-10-30",
                    "close": 23053.1,
                    "change": {"1m": 0.015},
                },
                {
                    "name": "Nifty Smallcap 250",
                    "as_of": "2026-10-30",
                    "close": 16764.5,
                    "change": {"1m": -0.055},
                },
            ],
            "vix": {"level": 15.3, "percentile_1y": 71.3, "median_1y": 13.2},
        },
        "breadth": {
            "available": True,
            "stocks": 2563,
            "latest": {"above_50": 16.5, "new_highs": 26, "new_lows": 206},
            "series": {"above_50": [40.0] * 200 + [30.0] * 40 + [16.5]},
            "new_high_names": [{"symbol": "KOTAKBANK"}],
            "new_low_names": [{"symbol": "SUZLON"}],
        },
        "positioning": {
            "available": True,
            "participants": [
                {
                    "participant": "FII",
                    "index_futures_long_share": 0.111,
                    "usual": 0.12,
                    "percentile": 38.6,
                }
            ],
        },
        "valuation": {
            "indices": [
                {
                    "name": "Nifty 50",
                    "pe": {"value": 19.3, "percentile": 1.3, "median": 22.1, "since": "2021-04-01"},
                }
            ]
        },
        "options": {
            "available": True,
            "pcr_oi": 1.04,
            "pcr_oi_before": 0.70,
            "expiry": "2026-11-03",
            "as_of": "2026-10-28",
        },
        "pulse": {"cards": [{"key": "trend", "word": "Downtrend"}]},
        "sectors": {
            "sectors": [
                {"name": "Nifty IT", "relative": {"1m": 0.16}},
                {"name": "Nifty Metal", "relative": {"1m": -0.05}},
            ]
        },
        "delivery": {"stocks": [{"symbol": "NIACL", "delivery_pct": 62.2, "usual_pct": 23.6}]},
    }


CLOSES = [24000.0] * 150 + [23300.0] * 30 + [22700.0] * 19 + [23053.1]


def test_matters_ranks_the_most_unusual_and_says_what_each_means() -> None:
    found = brief_content.matters(
        _ctx(), fii_nets=[float(x % 7 - 3) * 1000 for x in range(30)], closes=CLOSES, lv=LV
    )
    assert len(found) == 3
    assert [m["key"] for m in found] == ["breadth", "options", "divergence"]
    assert all(m["meaning"] and m["page"].startswith("docs/METRICS/") for m in found)
    assert found[0]["fact"].startswith("16% of NSE stocks are above their 50-day average")
    scores = [m["score"] for m in found]
    assert scores == sorted(scores, reverse=True) and min(scores) >= 25


def test_a_quiet_market_says_nothing_matters() -> None:
    calm = _ctx()
    calm["strip"]["vix"]["percentile_1y"] = 55.0
    calm["breadth"]["latest"]["above_50"] = 40.0
    calm["options"]["pcr_oi"] = 0.71
    calm["strip"]["indices"][1]["change"]["1m"] = 0.01
    calm["valuation"]["indices"][0]["pe"]["percentile"] = 50.0
    calm["pulse"] = {}
    assert brief_content.matters(calm, fii_nets=[], closes=CLOSES, lv=LV) == []


def test_coming_up_marks_held_names_in_the_ban_and_says_what_is_not_covered() -> None:
    reports = {
        "ban": {"available": True, "as_of": "2026-10-30", "symbols": ["SAIL", "KAYNES"]},
        "ipos": {"open": [{"company": "Acme Ltd"}]},
    }
    events = [
        {
            "title": "Non-Farm Payrolls",
            "country": "USD",
            "time": "2026-11-06T13:30:00+00:00",
            "impact": "High",
        },
        {"title": "FOMC", "country": "USD", "time": "2026-10-31T18:00:00+00:00", "impact": "High"},
    ]
    out = brief_content.coming_up(
        today=date(2026, 10, 31), ctx=_ctx(), events=events, reports=reports, held={"SAIL"}
    )
    whats = [i["what"] for i in out["items"]]
    assert whats[0] == "Nifty options expiry (in 3 days)"
    assert "USD FOMC" in whats and not any("Payrolls" in w for w in whats)
    ban = next(i for i in out["items"] if i["what"].startswith("F&O ban"))
    assert ban["why"].startswith("You hold SAIL.")
    assert any("results" in n for n in out["not_covered"])


def test_attention_puts_loss_limits_first() -> None:
    books = [
        {
            "strategy": "a",
            "status": "active",
            "drawdown": 0.094,
            "reduce_at": 0.1,
            "symbols": [],
            "next_rebalance": "in 3 session(s)",
        },
        {
            "strategy": "b",
            "status": "active",
            "drawdown": 0.01,
            "reduce_at": 0.1,
            "symbols": ["SAIL"],
            "next_rebalance": "in 1 session(s)",
        },
        {"strategy": "c", "status": "halted", "drawdown": 0.3, "reduce_at": 0.1},
    ]
    out = brief_content.attention(books, {"SAIL"})
    assert [a["book"] for a in out] == ["a", "b", "b"]
    assert out[0]["why"].startswith("9.4% below its peak")


def test_review_compares_this_morning_with_the_close() -> None:
    read = trader_read.build(
        _ctx(), closes=CLOSES, flows={"available": False}, books=[], day="2026-10-30", lv=LV
    )
    morning = {
        "range": {"low": 22900, "high": 23200},
        "rows": [{"signal": "Breadth", "word": "neutral"}],
    }
    lines = brief_content.review(morning, read, 23053.1, "2026-10-30", "2026-10-30")
    assert lines[0].startswith("Nifty closed at 23,053.1, inside this morning's one-day range")
    assert "Breadth: neutral → weak." in lines
    assert brief_content.review(morning, read, 23053.1, "2026-10-29", "2026-10-30")[0].startswith(
        "Today's close is not held yet"
    )
    assert brief_content.review(None, read, 1.0, "d", "d") == []


def test_the_brief_reads_answer_first_and_telegram_fits_eight_lines() -> None:
    inputs = {
        "context": _ctx(),
        "closes": CLOSES,
        "flows": {"available": False},
        "books": [],
        "events": [],
        "reports": {},
    }
    read = trader_read.build(
        _ctx(), closes=CLOSES, flows={"available": False}, books=[], day="2026-10-31", lv=LV
    )
    brief = market_brief.build_brief("pre-open", "2026-10-31", inputs, read, LV, None)
    # Cash flows are not held in this fixture, so the headline says it is incomplete (ADR-101).
    assert brief["tone"] == "incomplete" and brief["missing"] == ["Cash flows"]
    assert brief["range"]["low"] == 22831
    text = market_brief.brief_text(brief, trader_read.render(read), "")
    order = [
        text.index(h)
        for h in (
            "WHAT MATTERS TODAY",
            "LEVELS AND WHAT",
            "COMING UP",
            "YOUR BOOKS",
            "UNDERNEATH",
            "TRADER'S READ",
        )
    ]
    assert order == sorted(order)
    message = brief_content.telegram(brief)
    assert len(message.splitlines()) <= 8 and message.endswith("Market brief")


def test_a_closed_day_gets_one_markets_closed_note_per_break(
    tmp_path: Any, monkeypatch: Any
) -> None:
    from datetime import UTC, datetime

    from eulerlab.agents import runtime
    from eulerlab.agents.spec import AgentSpec, effective
    from eulerlab.ingest import holidays

    ctx = _ctx()
    ctx["strip"]["indices"][0]["change"]["1w"] = 0.02
    monkeypatch.setattr(
        holidays, "load_holidays", lambda cache_dir: frozenset({date(2026, 11, 10)})
    )
    monkeypatch.setattr(market_brief, "_context", lambda notes: ctx)
    monkeypatch.setattr(market_brief, "_world", lambda notes, fetch: [])
    monkeypatch.setattr(market_brief, "_events", lambda day: [])
    monkeypatch.setattr(market_brief, "_books", list)
    monkeypatch.setattr(market_brief, "_flows", lambda: {"available": False})
    monkeypatch.setattr(market_brief, "_closes", lambda: CLOSES)
    monkeypatch.setattr(market_brief, "_reports", dict)
    monkeypatch.setattr(market_brief, "_results", lambda day: {"upcoming": [], "since": ""})
    monkeypatch.setattr(market_brief, "_history", lambda books: {})
    spec = AgentSpec(
        name="market_brief",
        title="brief",
        job="a job for the test",
        worker="eulerlab.agents.workers.market_brief",
    )
    agents = {"market_brief": effective(spec, None)}

    def run(when: datetime) -> Any:
        return runtime.run("market_brief", root=tmp_path, agents=agents, now=when)

    saturday = run(datetime(2026, 10, 31, 4, 0, tzinfo=UTC))
    brief = saturday.data["brief"]
    assert saturday.status == "ok" and brief["mode"] == "weekend"
    assert brief["headline"].startswith("Markets closed today (weekend); last session 2026-10-30.")
    assert brief["review_title"] == "The week in review"
    assert brief["review"][0] == "Nifty 50: +2.0% over the week, to 23,053.1 (2026-10-30)."
    assert brief_content.telegram(brief).startswith("MARKETS CLOSED · 2026-10-31")
    sunday = run(datetime(2026, 11, 1, 4, 0, tzinfo=UTC))
    assert sunday.status == "skipped" and "already written" in sunday.summary
    holiday = run(datetime(2026, 11, 10, 4, 0, tzinfo=UTC))
    assert holiday.status == "skipped"  # same data date as Saturday's note: one note per break
    assert holidays.is_session(date(2026, 11, 9), frozenset()) and not holidays.is_session(
        date(2026, 11, 8), frozenset()
    )
    assert holidays.is_session(date(2026, 11, 9), frozenset()) and not holidays.is_session(
        date(2026, 11, 10), frozenset({date(2026, 11, 10)})
    )
