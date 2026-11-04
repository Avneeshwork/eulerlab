"""Market-wide news: landing, the derived table, tone, what is judged, and the impact check (ADR-134)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import brief_content
from eulerlab.forecast import news_tone
from eulerlab.ingest import market_news

S = market_news.setup()
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


def _story(title: str, hours_ago: float = 2, desc: str = "", url: str = "") -> dict[str, Any]:
    return {
        "title": title,
        "description": desc,
        "url": url or f"https://example.com/{abs(hash(title))}",
        "published": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S +0000"),
    }


def _tone(texts: list[str] | Any) -> list[dict[str, float]]:
    """A stand-in scorer: negative when the text says fall, war or fear."""
    out = []
    for t in texts:
        bad = any(w in t.lower() for w in ("fall", "war", "fear", "drop"))
        s = -0.8 if bad else 0.6
        out.append({"positive": max(s, 0), "negative": max(-s, 0), "neutral": 0.2, "score": s})
    return out


def test_relevance_keeps_market_news_and_drops_the_rest() -> None:
    assert market_news.relevant("RBI holds repo rate", "", S)
    assert market_news.relevant("Iran says war is near", "", S)
    assert not market_news.relevant(
        "Kolkata man loses Rs 41,000 to OTP fraud", "share market tips", S
    )
    assert not market_news.relevant("Salman Khan returns to singing", "", S)


def test_windows_stay_inside_what_currents_accepts() -> None:
    spans = market_news.windows(NOW - timedelta(days=30), NOW)
    assert all(b - a < timedelta(days=7) for a, b in spans)
    assert spans[0][1] == NOW and spans[-1][0] == NOW - timedelta(days=30)


def test_refresh_lands_merges_and_scores_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, datetime]] = []

    def fake(
        search: market_news.Search, key: str, s: Any, now: datetime, a: datetime, b: datetime
    ) -> list[dict[str, Any]]:
        calls.append((search.keywords, a))
        body = {
            "news": [
                _story(f"Nifty falls as {search.keywords} worries grow"),
                _story("Sensex rises on FII buying"),
            ]
        }
        return market_news.parse_currents(body, search, s, now)

    monkeypatch.setattr(market_news, "api_key", lambda: "k")
    monkeypatch.setattr(market_news, "search_currents", fake)
    scored: list[int] = []

    def counting(texts: Any) -> list[dict[str, float]]:
        scored.append(len(texts))
        return _tone(texts)

    first = market_news.refresh(now=NOW, s=S, scorer=counting, model="m@1", root=tmp_path)
    rows = market_news.held()
    # One story per search plus one shared headline, found by every search.
    assert first["held"] == len(S.searches) + 1 and not first["failed"]
    shared = next(r for r in rows if r["title"] == "Sensex rises on FII buying")
    assert len(shared["symbols"]) == len({s.topic for s in S.searches})
    assert all("tone" in r for r in rows if r["matched"]) and rows[0]["tone"]["model"] == "m@1"
    landed = tmp_path / "market" / "2026-11.jsonl.gz"
    assert len(gzip.decompress(landed.read_bytes()).decode().splitlines()) == first["held"]
    # Backfill: five windows a search, none reaching 30 days back.
    assert first["requests"] == len(S.searches) * 5
    assert min(a for _, a in calls) > NOW - timedelta(days=30)
    later = market_news.refresh(
        now=NOW + timedelta(hours=2), s=S, scorer=counting, model="m@1", root=tmp_path
    )
    assert later["new"] == 0 and later["scored"] == 0 and len(scored) == 1
    assert later["requests"] == len(S.searches)  # only since the last story
    assert market_news.held()[0]["knowledge_time"] == NOW.isoformat()  # first sighting kept


def test_google_news_stands_in_when_currents_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rss = b"""<rss><channel><item><title>Rupee falls to record low - Reuters</title>
    <link>https://x/1</link><pubDate>Wed, 04 Nov 2026 01:00:00 GMT</pubDate><source>Reuters</source></item>
    </channel></rss>"""

    def broken(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise ValueError("currents answered 429")

    monkeypatch.setattr(market_news, "api_key", lambda: "k")
    monkeypatch.setattr(market_news, "search_currents", broken)
    monkeypatch.setattr(
        market_news, "search_rss", lambda search, s, now: market_news.parse_rss(rss, search, s, now)
    )
    out = market_news.refresh(now=NOW, s=S, scorer=None, root=tmp_path)
    rows = market_news.held()
    assert out["failed"] and rows[0]["title"] == "Rupee falls to record low"
    assert rows[0]["provider"] == "google_news" and rows[0]["publisher"] == "Reuters"


def _held(titles: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    rows = []
    for i, (title, topic, score) in enumerate(titles):
        rows.append(
            {
                "guid": f"g{i}",
                "title": title,
                "description": "",
                "symbols": [topic],
                "matched": True,
                "event_time": (NOW - timedelta(hours=1 + i % 5)).isoformat(),
                "knowledge_time": (NOW - timedelta(hours=1)).isoformat(),
                "tone": {"score": score},
            }
        )
    return rows


def test_the_judged_stories_skip_recaps_and_draw_each_theme() -> None:
    rows = _held(
        [
            ("Sensex rises over 1,000 points on FII buying", "india_market", 1.0),
            ("Stock market LIVE: Nifty opens lower", "india_market", -1.0),
            ("Iran warns of strikes on shipping lanes", "geopolitics", -0.2),
            ("RBI flags inflation risk from crude", "policy", -0.5),
            ("Brent falls 3% on talks hope", "commodities", -0.9),
            ("SEBI proposes LTCG relief", "india_market", 0.9),
        ]
    )
    picked = [r["title"] for r in news_tone.to_judge(rows, NOW, 4)]
    assert "Sensex rises over 1,000 points on FII buying" not in picked
    assert "Stock market LIVE: Nifty opens lower" not in picked
    assert picked[0] == "Iran warns of strikes on shipping lanes"  # geopolitics first, however mild
    assert picked == [
        "Iran warns of strikes on shipping lanes",
        "RBI flags inflation risk from crude",
        "Brent falls 3% on talks hope",
        "SEBI proposes LTCG relief",
    ]


def test_the_impact_check_drops_lines_that_do_not_hold_up() -> None:
    items = _held(
        [
            ("Brent falls 3% on talks hope", "commodities", -0.9),
            ("Iran warns of strikes", "geopolitics", -0.4),
        ]
    )
    answer = "\n".join(
        [
            '{"i": 1, "direction": "up", "severity": "medium", "sectors": ["Paints", "Aviation"], "why": "A 3% fall in crude cuts costs for India."}',
            '{"i": 2, "direction": "down", "severity": "high", "sectors": ["Energy"], "why": "A strike could lift oil 20%."}',
            '{"i": 2, "direction": "sideways", "severity": "high", "why": "unclear"}',
            '{"i": 7, "direction": "down", "severity": "high", "why": "no such story"}',
            "not json",
        ]
    )
    got = news_tone.parse_impact(answer, items)
    # Story 2's only valid line used a figure the story does not hold (20%): dropped.
    assert [g["title"] for g in got] == ["Brent falls 3% on talks hope"]
    assert got[0]["direction"] == "up" and got[0]["tone"] == -0.9
    ok = news_tone.parse_impact(
        '{"i": 2, "direction": "down", "severity": "high", "sectors": [], "why": "War risk near the Gulf hurts India."}',
        items,
    )
    assert news_tone.shocks(ok) == ok


def test_summary_and_brief_sections_say_tone_impact_shock_and_crash_risk() -> None:
    rows = _held(
        [
            ("Iran warns of war", "geopolitics", -0.8),
            ("RBI holds rates", "policy", 0.4),
            ("Rupee firm", "currency", 0.5),
        ]
    )
    s = news_tone.summary(rows, NOW)
    assert s["available"] and s["stories"] == 3 and s["negative"] == 1 and s["percentile"] is None
    impacts = news_tone.parse_impact(
        '{"i": 1, "direction": "down", "severity": "high", "sectors": ["Energy"], "why": "War near the Gulf would lift crude."}\n'
        '{"i": 2, "direction": "up", "severity": "low", "sectors": [], "why": "Steady rates help."}',
        rows,
    )
    tail = {
        "available": True,
        "vix_band": "high",
        "since": "2016-01-20",
        "sessions": 748,
        "down2": 0.053,
        "down3": 0.02,
        "worst": -12.98,
        "worst_day": "2020-03-23",
        "all_down2": 0.022,
        "all_down3": 0.008,
    }
    sections = brief_content.news_sections(
        {"summary": s, "impacts": impacts, "items": rows, "model": "m@1"},
        {"tail": tail, "check": {"below_band": 0.12, "n": 500}},
    )
    news, crash = (x["lines"] for x in sections)
    assert news[0].startswith("Tone of 3 market stories in the last 24 hours: +0.03")
    assert any(x.startswith("SHOCK RISK: Iran warns of war") for x in news)
    assert any(x.startswith("▲ low · RBI holds rates") for x in news)
    assert "5.3% of 748 sessions" in crash[0] and "below the forecast band on 12%" in crash[1]
    text = brief_content.telegram(
        {
            "mode": "pre-open",
            "day": "2026-11-04",
            "headline": "h",
            "matters": [{"title": "a", "fact": "b"}] * 3,
            "news_summary": s,
            "shocks": ["Iran warns of war"],
        }
    )
    assert "News tone +0.03 (1 negative of 3); shock risk: Iran warns of war" in text
    assert len(text.splitlines()) <= 8


def test_currents_dates_parse_and_bad_ones_are_dropped() -> None:
    body = {"news": [_story("Nifty steady"), {"title": "no date", "published": "yesterday"}]}
    rows = market_news.parse_currents(body, S.searches[0], S, NOW)
    assert len(rows) == 1 and rows[0]["event_time"] == (NOW - timedelta(hours=2)).isoformat()
    assert json.dumps(rows)  # serialisable as landed
