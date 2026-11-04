"""News tone and possible impact for the brief (ADR-134, research 148).

Two layers, because research 148's test on 39 real headlines showed one is not
enough:

1. **Tone, for every relevant story.** A financial-news sentiment model run
   locally: `mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`
   (Apache-2.0, 82M parameters, fine-tuned on Financial PhraseBank), pinned to
   one revision so the same text always gets the same score. Score =
   P(positive) - P(negative), from -1 to +1. It reads the headline and the
   summary. It scores the words, not the economics: "crude falls below $104"
   scores negative although cheaper oil helps India. ProsusAI's FinBERT was
   not used: its weights are non-commercial only.
2. **Impact, for the few that matter.** One model request per brief reads the
   `judge` most relevant stories of the last day and says, for each, whether
   it is likely to push Indian equities up or down, how serious it is, which
   sectors it touches and why. The answer must name stories by number; any
   line that does not parse, names no story, or uses a figure the story does
   not hold is dropped.

Neither feeds the forecast's numbers until a test shows news helps (T-4433):
the brief shows them beside it. Nothing here trades, logs a trial or reads the
holdout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from eulerlab.ingest.market_news import Scorer

MODEL = "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
REVISION = "ae0eab9ad336d7d548e0efe394b07c04bcaf6e91"
MODEL_ID = f"{MODEL}@{REVISION[:7]}"
IST = ZoneInfo("Asia/Kolkata")
# A story scoring past this either way counts as positive or negative.
CLEAR = 0.3
DIRECTIONS = ("up", "down", "mixed", "none")
SEVERITY = ("low", "medium", "high")


def scorer() -> Scorer | None:
    """The local tone model, or None when the `news` extra is not installed."""
    try:
        from transformers import pipeline
    except ImportError:
        return None
    clf = pipeline("text-classification", model=MODEL, revision=REVISION, top_k=None)

    def score(texts: Sequence[str]) -> list[dict[str, float]]:
        out: list[dict[str, float]] = []
        results = clf(list(texts), batch_size=16, truncation=True, max_length=128)
        for res in cast(list[list[dict[str, Any]]], results):
            p = {str(x["label"]).lower(): float(x["score"]) for x in res}
            pos, neg = p.get("positive", 0.0), p.get("negative", 0.0)
            out.append(
                {
                    "positive": round(pos, 4),
                    "negative": round(neg, 4),
                    "neutral": round(p.get("neutral", 0.0), 4),
                    "score": round(pos - neg, 4),
                }
            )
        return out

    return score


def _when(row: Mapping[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(str(row[key]))


def known(rows: Sequence[Mapping[str, Any]], as_of: datetime) -> list[Mapping[str, Any]]:
    """Relevant, scored stories known at `as_of`."""
    return [
        r for r in rows if r.get("matched") and "tone" in r and _when(r, "knowledge_time") <= as_of
    ]


def summary(rows: Sequence[Mapping[str, Any]], as_of: datetime, days: int = 30) -> dict[str, Any]:
    """The last 24 hours' tone against each day's in the last `days`."""
    held = known(rows, as_of)
    recent = [r for r in held if as_of - timedelta(hours=24) <= _when(r, "event_time") <= as_of]
    if not recent:
        return {"available": False, "reason": "no scored story in the last 24 hours"}
    by_day: dict[str, list[float]] = {}
    for r in held:
        t = _when(r, "event_time")
        if as_of - timedelta(days=days) <= t <= as_of - timedelta(hours=24):
            by_day.setdefault(t.astimezone(IST).date().isoformat(), []).append(
                float(r["tone"]["score"])
            )
    daily = [sum(v) / len(v) for v in by_day.values() if len(v) >= 3]
    scores = [float(r["tone"]["score"]) for r in recent]
    mean = sum(scores) / len(scores)
    topics: dict[str, list[float]] = {}
    for r in recent:
        for t in r.get("symbols") or []:
            topics.setdefault(str(t), []).append(float(r["tone"]["score"]))
    return {
        "available": True,
        "stories": len(recent),
        "mean": round(mean, 3),
        "positive": sum(s > CLEAR for s in scores),
        "negative": sum(s < -CLEAR for s in scores),
        "days": len(daily),
        "percentile": round(sum(d <= mean for d in daily) / len(daily) * 100)
        if len(daily) >= 10
        else None,
        "usual": round(sorted(daily)[len(daily) // 2], 3) if daily else None,
        "topics": {k: round(sum(v) / len(v), 3) for k, v in sorted(topics.items())},
        "topic_counts": {k: len(v) for k, v in sorted(topics.items())},
    }


def _stem(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower())[:6])


# Reports of how the market already moved ("Sensex rises 1,000 points", "Stock market
# LIVE"): the move is in the prices the forecast already reads, so they are not judged.
RECAP = re.compile(
    r"\b(sensex|nifty|stock market|markets?|d-street|dalal street)\b.*\b(rises?|rose|falls?|fell|gains?|"
    r"jumps?|surges?|slips?|drops?|tumbles?|closes?|opens?|ends?|extends?|live|today|points?|rally)\b",
    re.IGNORECASE,
)
# Themes in the order they are drawn from: what prices cannot see yet comes first.
PRIORITY = ("geopolitics", "policy", "global", "commodities", "currency", "india_market")


def recap(title: str) -> bool:
    return bool(RECAP.search(title))


def to_judge(rows: Sequence[Mapping[str, Any]], as_of: datetime, n: int) -> list[Mapping[str, Any]]:
    """Up to `n` stories of the last 24 hours to judge: no market recaps, one per near-identical
    headline, drawn from each theme in turn (`PRIORITY`), strongest tone first within a theme."""
    recent = [
        r
        for r in known(rows, as_of)
        if as_of - timedelta(hours=24) <= _when(r, "event_time") <= as_of
        and not recap(str(r["title"]))
    ]
    queues: dict[str, list[Mapping[str, Any]]] = {}
    for r in sorted(recent, key=lambda r: (-abs(float(r["tone"]["score"])), str(r["guid"]))):
        topics = [str(x) for x in r.get("symbols") or []] or ["other"]
        first = min(topics, key=lambda x: PRIORITY.index(x) if x in PRIORITY else len(PRIORITY))
        queues.setdefault(first, []).append(r)
    order = sorted(queues, key=lambda x: PRIORITY.index(x) if x in PRIORITY else len(PRIORITY))
    out: list[Mapping[str, Any]] = []
    stems: set[str] = set()
    while len(out) < n and any(queues.values()):
        for topic in order:
            while queues[topic]:
                r = queues[topic].pop(0)
                stem = _stem(str(r["title"]))
                if stem not in stems:
                    stems.add(stem)
                    out.append(r)
                    break
            if len(out) == n:
                break
    return out


QUESTION = (
    "You judge news for a trader in Indian equities (Nifty 50). For each numbered story below, "
    "answer one JSON object per line, nothing else: "
    '{"i": <story number>, "direction": "up"|"down"|"mixed"|"none", "severity": "low"|"medium"|"high", '
    '"sectors": [up to 3 Indian market sectors], "why": "<one sentence>"}. '
    "direction is the likely push on Indian equities over the next session or two, not the story's tone: "
    "cheaper crude helps India, a rate hike hurts stocks, war or sanctions near India hurt. "
    "severity is high only for news that can move the whole market, such as war, a policy surprise or a "
    "crash abroad. A story that only reports how the market already moved is not news: severity low. "
    "Use no figure the story does not give. Judge only what the story says."
)


def numbered(items: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"{i}. {r['title']}" + (f" — {r['description']}" if r.get("description") else "")
        for i, r in enumerate(items, 1)
    )


def _figures(text: str) -> set[str]:
    return {m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def parse_impact(answer: str, items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The model's lines that parse, name a story, and use only that story's figures."""
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for line in answer.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(got, dict):
            continue
        i = got.get("i")
        if not isinstance(i, int) or not 1 <= i <= len(items) or i in seen:
            continue
        direction, severity = got.get("direction"), got.get("severity")
        why = str(got.get("why") or "").strip()[:240]
        if direction not in DIRECTIONS or severity not in SEVERITY or not why:
            continue
        story = items[i - 1]
        if not _figures(why) <= _figures(f"{story['title']} {story.get('description') or ''}"):
            continue
        sectors = [str(x)[:30] for x in got.get("sectors") or [] if isinstance(x, str)][:3]
        seen.add(i)
        out.append(
            {
                "title": story["title"],
                "publisher": story.get("publisher", ""),
                "link": story.get("link", ""),
                "event_time": story["event_time"],
                "tone": float(story["tone"]["score"]),
                "direction": direction,
                "severity": severity,
                "sectors": sectors,
                "why": why,
            }
        )
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: (order[x["severity"]], x["direction"] == "none"))


def shocks(impacts: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """High-severity stories judged to push the market down."""
    return [x for x in impacts if x["severity"] == "high" and x["direction"] == "down"]
