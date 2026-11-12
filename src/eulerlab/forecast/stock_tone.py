"""News tone for each stock, from the per-instrument headlines (ADR-135).

`ingest/news.py` lands Google News headlines per NSE symbol. A headline counts
for a stock only when it names it (`news.strong_match`: the ticker or the
first distinctive words of the registered name), the test the company page
already uses, and is not a formulaic quote page (`news.formulaic`). Each
headline is scored once by the tone model (`SCORES`, by guid), corrected by
the news rules where one fits, and each stock gets the last `days` days'
mean, counts and its headlines (`OUT`).

The brief shows the stocks in the paper books and the stocks with the most
one-sided news; the company page shows each headline's tone. Nothing trades
on it.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from eulerlab.forecast import news_rules
from eulerlab.forecast.news_tone import CLEAR
from eulerlab.ingest.market_news import Scorer
from eulerlab.paths import data_path

SCORES = data_path("derived/stock_news_scores.jsonl")
OUT = data_path("derived/stock_news_tone.json")
# Headlines kept per stock in `OUT`, newest first.
KEEP = 30


def _scores(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or SCORES
    if not p.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out.setdefault(str(row["guid"]), row)
    return out


def headlines(
    files: Iterable[bytes], names: Mapping[str, str], since: datetime, until: datetime
) -> list[dict[str, Any]]:
    """Headlines that name their stock, published in [since, until], one row per stock and story."""
    from eulerlab.ingest import news

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for blob in files:
        for line in gzip.decompress(blob).decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            title = str(row.get("title") or "")
            try:
                when = datetime.fromisoformat(str(row.get("event_time")))
            except ValueError:
                continue
            if not since <= when <= until or news.formulaic(title):
                continue
            for symbol in row.get("symbols") or []:
                if news.strong_match(title, str(symbol), names.get(str(symbol), "")):
                    out[(str(symbol), str(row.get("guid") or title))] = {
                        "symbol": str(symbol),
                        "guid": str(row.get("guid") or title),
                        "title": title,
                        "link": str(row.get("link") or ""),
                        "publisher": str(row.get("publisher") or ""),
                        "event_time": when.isoformat(),
                    }
    return sorted(out.values(), key=lambda r: (r["symbol"], r["event_time"]), reverse=True)


def build(
    *,
    now: datetime,
    scorer: Scorer | None,
    model: str,
    rules: Sequence[news_rules.Rule],
    files: Iterable[bytes] | None = None,
    names: Mapping[str, str] | None = None,
    days: int = 7,
    scores_path: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Score new headlines, then each stock's last `days` days. Saved to `OUT`."""
    from eulerlab.features import company_page
    from eulerlab.ingest import news

    rows = headlines(
        files if files is not None else company_page.news_files(months=2),
        names if names is not None else news.load_names(),
        now - timedelta(days=days),
        now,
    )
    cache = _scores(scores_path)
    todo = sorted({r["guid"]: r["title"] for r in rows if r["guid"] not in cache}.items())
    if todo and scorer is not None:
        tones = scorer([title for _, title in todo])
        p = scores_path or SCORES
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as handle:
            for (g, _), tone in zip(todo, tones, strict=True):
                row = {"guid": g, "model": model, **tone}
                cache[g] = row
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    stocks: dict[str, dict[str, Any]] = {}
    for r in rows:
        held = cache.get(r["guid"])
        if held is None:
            continue
        rule = news_rules.match(r["title"], rules)
        score = news_rules.corrected(float(held["score"]), rule)
        s = stocks.setdefault(r["symbol"], {"items": []})
        s["items"].append(
            r | {"tone": float(held["score"]), "score": score, "rule": rule.id if rule else None}
        )
    for s in stocks.values():
        scores = [i["score"] for i in s["items"]]
        s |= {
            "n": len(scores),
            "mean": round(sum(scores) / len(scores), 3),
            "positive": sum(x > CLEAR for x in scores),
            "negative": sum(x < -CLEAR for x in scores),
            "items": s["items"][:KEEP],
        }
    out = {
        "as_of": now.isoformat(),
        "days": days,
        "model": model,
        "unscored": 0 if scorer is not None else len(todo),
        "stocks": dict(sorted(stocks.items())),
    }
    p = out_path or OUT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, sort_keys=True), encoding="utf-8")
    return out


def held(path: Path | None = None) -> dict[str, Any]:
    p = path or OUT
    if not p.exists():
        return {}
    loaded = json.loads(p.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def for_symbol(symbol: str, path: Path | None = None) -> dict[str, Any] | None:
    got = held(path)
    stock = (got.get("stocks") or {}).get(symbol)
    if not stock:
        return None
    return {"days": got.get("days"), "as_of": got.get("as_of"), "model": got.get("model"), **stock}


def lines(
    table: Mapping[str, Any], held_symbols: Iterable[str], *, top: int = 5, min_n: int = 3
) -> list[str]:
    """The brief's lines: each held stock with news, then the most one-sided of the rest."""
    stocks: Mapping[str, Mapping[str, Any]] = table.get("stocks") or {}
    if not stocks:
        return []
    days = table.get("days")

    def say(sym: str, s: Mapping[str, Any]) -> str:
        latest = s["items"][0]
        return (
            f"{sym}: tone {s['mean']:+.2f} over {s['n']} {'story' if s['n'] == 1 else 'stories'} in {days} days "
            f"({s['positive']} positive, {s['negative']} negative). Latest: {latest['title'][:100]}"
            + (f" (rule {latest['rule']})" if latest.get("rule") else "")
        )

    held_set = sorted(set(held_symbols))
    with_news = sorted(
        (sym for sym in held_set if sym in stocks), key=lambda x: (-stocks[x]["n"], x)
    )
    out = [say(sym, stocks[sym]) for sym in with_news[: top * 2]]
    if len(with_news) > top * 2:
        out.append(
            "Other holdings with news: "
            + "; ".join(
                f"{sym} {stocks[sym]['mean']:+.2f} ({stocks[sym]['n']})"
                for sym in with_news[top * 2 :]
            )
            + "."
        )
    quiet = [sym for sym in held_set if sym not in stocks]
    if quiet:
        out.append(f"No news naming {', '.join(quiet[:12])} in {days} days.")
    rest = sorted(
        ((sym, s) for sym, s in stocks.items() if sym not in held_set and s["n"] >= min_n),
        key=lambda kv: (-abs(kv[1]["mean"]), kv[0]),
    )[:top]
    if rest:
        out.append(
            "Most one-sided news elsewhere: "
            + "; ".join(f"{sym} {s['mean']:+.2f} ({s['n']})" for sym, s in rest)
            + "."
        )
    if table.get("unscored"):
        out.append(f"{table['unscored']} headlines not scored: the tone model is not installed.")
    return out
