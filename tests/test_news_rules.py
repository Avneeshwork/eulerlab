"""The news rules knowledge base, its learning, NewsData and per-stock tone (ADR-135)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import brief_content
from eulerlab.forecast import news_rules, news_tone, stock_tone
from eulerlab.ingest import market_news

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=UTC)
BOOK = news_rules.seeds()


def _id(text: str) -> str | None:
    rule = news_rules.match(text, BOOK.rules)
    return rule.id if rule else None


def test_the_written_rules_read_the_economics_not_the_words() -> None:
    assert _id("Oil slips after early surge, Brent falls 3%") == "crude-down"
    assert _id("Crude oil jumps as Gulf tensions rise") == "crude-up"
    assert _id("OPEC+ output cut sends oil lower") is None  # `unless`
    assert _id("SBI chair backs 50 bp rate hike in December") == "rate-hike"
    assert _id("Rupee falls to record low against the dollar") == "rupee-weak"
    assert _id("Missile strikes on Iran oil field") == "war-near"
    assert _id("Iran and Israel agree to ceasefire talks") == "ceasefire"
    assert _id("Kolkata man wins payout") is None
    rule = news_rules.match("Brent falls 3%", BOOK.rules)
    assert news_rules.corrected(-1.0, rule) == 1.0
    assert news_rules.corrected(-0.1, rule) == news_rules.FLOOR  # neutral words, clear economics
    assert news_rules.corrected(-0.4, None) == -0.4


def _judge(title: str, direction: str) -> dict[str, Any]:
    return {
        "title": title,
        "description": "",
        "tone": 0.9,
        "direction": direction,
        "severity": "low",
    }


def test_a_learned_rule_switches_on_after_three_and_off_after_two_against(tmp_path: Path) -> None:
    log, learned = tmp_path / "j.jsonl", tmp_path / "l.json"
    rules = news_rules.all_rules(BOOK, learned)
    ups = [_judge(f"Gold rises to record {i}", "up") for i in range(2)]
    news_rules.record(ups, rules, NOW, log)
    assert news_rules.update(BOOK, now=NOW, log_path=log, path=learned) == []
    gold = next(r for r in news_rules.learned_rules(learned) if r.id == "learned-gold-up")
    assert gold.status == "proposed" and gold.agree == 2
    news_rules.record([_judge("Gold rises again on Fed bets", "up")], rules, NOW, log)
    changes = news_rules.update(BOOK, now=NOW, log_path=log, path=learned)
    assert changes == ["Switched on: learned-gold-up (up, 3 for, 0 against)"]
    on = news_rules.all_rules(BOOK, learned)
    assert _matched("Gold rises as the dollar slips", on) == "learned-gold-up"
    # The same title twice is logged once.
    assert news_rules.record([_judge("Gold rises again on Fed bets", "up")], on, NOW, log) == 0
    news_rules.record(
        [_judge("Gold rises, hurting jewellers", "down"), _judge("Gold rises on panic", "down")],
        on,
        NOW,
        log,
    )
    changes = news_rules.update(BOOK, now=NOW, log_path=log, path=learned)
    assert changes == ["Switched off: learned-gold-up (up, 3 for, 2 against)"]
    assert _matched("Gold rises as the dollar slips", news_rules.all_rules(BOOK, learned)) is None


def _matched(text: str, rules: list[news_rules.Rule]) -> str | None:
    rule = news_rules.match(text, rules)
    return rule.id if rule else None


def test_seeds_are_counted_never_switched_off_and_named_when_contested(tmp_path: Path) -> None:
    log, learned = tmp_path / "j.jsonl", tmp_path / "l.json"
    against = [_judge(f"Rupee falls but exporters cheer {i}", "up") for i in range(3)]
    news_rules.record(against, BOOK.rules, NOW, log)
    news_rules.update(BOOK, now=NOW, log_path=log, path=learned)
    evidence = news_rules.load_learned(learned)["seed_evidence"]
    assert evidence["rupee-weak"] == {"agree": 0, "disagree": 3}
    assert news_rules.contested(evidence, BOOK.learn.deactivate) == ["rupee-weak"]
    assert _matched("Rupee falls again", news_rules.all_rules(BOOK, learned)) == "rupee-weak"
    agree = news_rules.agreement(news_rules.judged(log))
    assert agree["rules"] == {"n": 3, "agree": 0.0} and agree["tone model"] == {
        "n": 3,
        "agree": 1.0,
    }


def test_with_no_model_request_the_rules_read_the_stories() -> None:
    items = [
        {
            "title": "Brent falls 3% on talks",
            "event_time": NOW.isoformat(),
            "tone": {"score": -0.9},
        },
        {"title": "Nykaa opens a new store", "event_time": NOW.isoformat(), "tone": {"score": 0.4}},
    ]
    got = news_tone.rule_impacts(items, BOOK.rules)
    assert len(got) == 1 and got[0]["direction"] == "up" and got[0]["severity"] == "rule"
    assert "(rule crude-down)" in got[0]["why"] and got[0]["sectors"] == [
        "except Oil & Gas producers"
    ]
    lines = brief_content.news_sections(
        {
            "summary": {"available": False, "reason": "x"},
            "impacts": got,
            "items": items,
            "by_rules": True,
        },
        {},
    )[0]["lines"]
    assert any("read by the news rules, not judged" in x for x in lines)
    assert any(x.startswith("▲ rule · Brent falls 3% on talks") for x in lines)


def test_newsdata_scores_are_kept_beside_ours_and_its_key_never_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    s = market_news.setup()
    body = {
        "status": "success",
        "results": [
            {
                "title": "Nifty slips as oil rises",
                "description": "Brent near $104",
                "link": "https://x/1",
                "pubDate": "2026-11-04 03:00:00",
                "source_name": "Mint",
                "sentiment": "negative",
                "sentiment_stats": {"positive": 5.0, "neutral": 15.0, "negative": 80.0},
            },
            {"title": "No stats", "link": "https://x/2", "pubDate": "2026-11-04 03:10:00"},
            {"title": "Bad date", "link": "https://x/3", "pubDate": "today"},
        ],
    }
    rows = market_news.parse_newsdata(body, s.searches[0], s, NOW)
    assert [r["title"] for r in rows] == ["Nifty slips as oil rises", "No stats"]
    assert rows[0]["newsdata_tone"]["score"] == -0.75 and "newsdata_tone" not in rows[1]
    assert rows[0]["event_time"] == "2026-11-04T03:00:00+00:00"

    def broken(*_a: Any) -> list[dict[str, Any]]:
        raise ValueError("newsdata answered status error")

    monkeypatch.setattr(market_news, "newsdata_key", lambda: "SECRET-KEY")
    monkeypatch.setattr(market_news, "search_newsdata", broken)
    out = market_news.refresh(now=NOW, s=s, root=tmp_path)
    assert out["newsdata_requests"] == len(s.searches)
    assert out["failed"] and not any("SECRET" in f for f in out["failed"])
    merged = market_news.merge(
        [{"guid": "g", "title": "t", "event_time": "1", "symbols": ["a"], "description": "d"}],
        [
            {
                "guid": "g",
                "title": "t",
                "event_time": "1",
                "symbols": ["b"],
                "newsdata_tone": {"score": 0.2},
            }
        ],
    )
    assert merged[0]["newsdata_tone"] == {"score": 0.2} and merged[0]["symbols"] == ["a", "b"]


def _equity_file(rows: list[dict[str, Any]]) -> bytes:
    return gzip.compress("".join(json.dumps(r) + "\n" for r in rows).encode())


def test_each_stock_gets_the_tone_of_headlines_that_name_it_scored_once(tmp_path: Path) -> None:
    when = (NOW - timedelta(days=1)).isoformat()
    blob = _equity_file(
        [
            {
                "guid": "a",
                "title": "ONGC profit falls as crude falls",
                "symbols": ["ONGC"],
                "event_time": when,
            },
            {"guid": "b", "title": "ONGC wins new block", "symbols": ["ONGC"], "event_time": when},
            {
                "guid": "c",
                "title": "Tatva Chintan gains",
                "symbols": ["ONGC"],
                "event_time": when,
            },  # not ONGC
            {
                "guid": "d",
                "title": "ONGC old story",
                "symbols": ["ONGC"],
                "event_time": (NOW - timedelta(days=30)).isoformat(),
            },
        ]
    )
    calls: list[int] = []

    def tone(texts: Any) -> list[dict[str, float]]:
        calls.append(len(texts))
        return [
            {"positive": 0.1, "negative": 0.8, "neutral": 0.1, "score": -0.7}
            if "falls" in t
            else {"positive": 0.9, "negative": 0.0, "neutral": 0.1, "score": 0.9}
            for t in texts
        ]

    kw: dict[str, Any] = {
        "now": NOW,
        "scorer": tone,
        "model": "m@1",
        "rules": BOOK.rules,
        "files": [blob],
        "names": {"ONGC": "Oil and Natural Gas Corporation Limited"},
        "scores_path": tmp_path / "s.jsonl",
        "out_path": tmp_path / "o.json",
    }
    table = stock_tone.build(**kw)
    ongc = table["stocks"]["ONGC"]
    assert ongc["n"] == 2 and calls == [2]
    # "crude falls" is the crude-down rule: up for the market (ONGC is the named exception).
    first = next(i for i in ongc["items"] if i["guid"] == "a")
    assert first["rule"] == "crude-down" and first["score"] == 0.7
    stock_tone.build(**kw)
    assert calls == [2]  # scored once
    lines = stock_tone.lines(table, ["ONGC", "TCS"])
    assert lines[0].startswith("ONGC: tone +0.80 over 2 stories in 7 days")
    assert lines[1] == "No news naming TCS in 7 days."
    one = stock_tone.for_symbol("ONGC", tmp_path / "o.json")
    assert one is not None and one["n"] == 2


def test_summary_reports_tone_corrected_by_rules_and_newsdata() -> None:
    rows = [
        {
            "guid": "1",
            "title": "Brent falls 3%",
            "matched": True,
            "symbols": ["commodities"],
            "event_time": (NOW - timedelta(hours=2)).isoformat(),
            "knowledge_time": NOW.isoformat(),
            "tone": {"score": -0.9},
            "newsdata_tone": {"score": -0.5},
        },
        {
            "guid": "2",
            "title": "RBI holds rates",
            "matched": True,
            "symbols": ["policy"],
            "event_time": (NOW - timedelta(hours=3)).isoformat(),
            "knowledge_time": NOW.isoformat(),
            "tone": {"score": 0.3},
        },
    ]
    s = news_tone.summary(rows, NOW, rules=BOOK.rules)
    assert s["mean"] == -0.3 and s["corrected_mean"] == 0.6 and s["corrected"] == 1
    assert s["newsdata_mean"] == -0.5 and s["newsdata_stories"] == 1
