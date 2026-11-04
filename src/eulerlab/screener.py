"""The stock screener: which liquid stocks each model would hold today, and why (ADR-136).

`build` loads the price panel once, builds today's view exactly as the engine
builds a decision date's view (rows adjusted for corporate actions known by
then), runs each model in `config/screener.yaml` and
`backtest/screener_models.py` on it, and writes `OUT`:

- for each model: its kind (long-term or swing), the stocks it would hold,
  and its stored screening backtest (Sharpe, return, drawdown, against
  NIFTYBEES over the same window);
- for each of the liquid 250: the reasons, i.e. momentum, trend, RSI(2),
  nearness to the 52-week high, liquidity, and, when known, quality and value
  ranks, F-score, ROE, P/E and P/B from the annual statements known by today,
  and its news tone; and which models pick it.

A list is what a model would hold, not advice. No model here has passed the
gate (CLAUDE.md: the gate decides), and every list carries its backtest and
that status. Nothing here trades, spends a trial or reads the holdout.
"""

from __future__ import annotations

import argparse
import json
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from eulerlab.backtest.event_driven import FAR_FUTURE
from eulerlab.backtest.strategy import MarketView, Strategy, decide
from eulerlab.config import CONFIG_DIR
from eulerlab.features.panel import PanelRow

OUT = Path("data/derived/screener.json")
HISTORY = Path("data/derived/screener_history.jsonl")
# Each kind's holding period: the sessions to its next decision.
HOLD = {"long": 21, "swing": 5}
BENCHMARK = "NIFTYBEES"


def config(config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or CONFIG_DIR) / "screener.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def isin_map(rows: Sequence[PanelRow]) -> dict[str, str]:
    """Each ticker's ISIN on its latest panel row (the ticker as it is listed now)."""
    out: dict[str, tuple[date, str]] = {}
    for r in rows:
        if r.isin and (r.symbol not in out or r.day >= out[r.symbol][0]):
            out[r.symbol] = (r.day, r.isin)
    return {s: isin for s, (_, isin) in out.items()}


def adjusted_view(
    histories: Mapping[str, Sequence[PanelRow]],
    day: date,
    lookback: int,
    events: Mapping[str, Sequence[tuple[date, float]]],
) -> MarketView:
    """The view a strategy deciding on `day` gets in `event_driven.run`: rows to `day`,
    the last `lookback`, each divided by the factors of actions after it and by `day`."""
    out: dict[str, list[PanelRow]] = {}
    for symbol, rows in histories.items():
        end = bisect_right([r.day for r in rows], day)
        if end == 0:
            continue
        window = list(rows[max(0, end - lookback) : end])
        known = [e for e in events.get(window[-1].isin, []) if e[0] <= day]
        if not known:
            out[symbol] = window
            continue
        adjusted: list[PanelRow] = []
        cumulative, cursor = 1.0, len(known) - 1
        for row in reversed(window):
            while cursor >= 0 and known[cursor][0] > row.day:
                cumulative *= known[cursor][1]
                cursor -= 1
            adjusted.append(row.adjusted(cumulative))
        adjusted.reverse()
        out[symbol] = adjusted
    return MarketView(as_of=day, history=out)


def _events() -> dict[str, list[tuple[date, float]]]:
    from eulerlab.features.panel import load_price_factor_store

    out: dict[str, list[tuple[date, float]]] = {}
    for record in load_price_factor_store().query(as_of=FAR_FUTURE):
        out.setdefault(record.key, []).append((record.event_time.date(), float(record.value)))
    for ev in out.values():
        ev.sort()
    return out


def backtests(paths: Sequence[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Each strategy's stored screening run, first file that holds it wins; and each file's benchmark."""
    runs: dict[str, dict[str, Any]] = {}
    bench: dict[str, Any] = {}
    for p in paths:
        path = Path(p)
        if not path.exists():
            continue
        got = json.loads(path.read_text(encoding="utf-8"))
        for r in got.get("runs") or []:
            if r.get("id") and r["id"] not in runs:
                runs[str(r["id"])] = r | {
                    "window": got.get("window"),
                    "benchmark": got.get("benchmark"),
                }
        bench.setdefault("window", got.get("window"))
        bench.setdefault("benchmark", got.get("benchmark"))
    return runs, bench


def _rank_pct(values: Mapping[str, float]) -> dict[str, float]:
    order = sorted(values, key=lambda s: (values[s], s))
    n = len(order)
    return {s: round(i / (n - 1) * 100) if n > 1 else 50.0 for i, s in enumerate(order)}


def reasons(view: MarketView, names: Sequence[str]) -> dict[str, dict[str, Any]]:
    """The facts a trader reads for each stock, from the same view the models saw."""
    from eulerlab.backtest import screener_models as sm
    from eulerlab.backtest.india_papers import MONTH, YEAR, nearness_to_52w_high

    out: dict[str, dict[str, Any]] = {}
    facts: dict[str, dict[str, float]] = {}
    for s in names:
        rows = view.history[s]
        c = [r.close for r in rows]
        last = rows[-1]
        turn = sorted(r.turnover for r in rows[-60:])
        s200 = sum(c[-200:]) / 200 if len(c) >= 200 else None
        rsi2 = sm.rsi(c)
        row: dict[str, Any] = {
            "close": round(last.close, 2),
            "change_1m": round(c[-1] / c[-1 - MONTH] - 1, 4) if len(c) > MONTH else None,
            "momentum_12_1": round(c[-1 - MONTH] / c[-1 - YEAR] - 1, 4) if len(c) > YEAR else None,
            "near_high": round(nh, 4) if (nh := nearness_to_52w_high(rows)) is not None else None,
            "above_200d": round(c[-1] / s200 - 1, 4) if s200 else None,
            "rsi2": round(rsi2, 1) if rsi2 is not None else None,
            "turnover_cr": round(turn[len(turn) // 2] / 1e7, 2) if turn else None,
        }
        f = sm.facts(last.isin, view.as_of, last.close)
        if f:
            facts[s] = f
            row |= {
                "fscore": int(f["fscore"]) if "fscore" in f else None,
                "roe": round(f["roe"], 4) if "roe" in f else None,
                "pe": round(1 / f["earnings_yield"], 1) if f.get("earnings_yield", 0) > 0 else None,
                "pb": round(1 / f["book_yield"], 2) if f.get("book_yield", 0) > 0 else None,
                "debt_equity": round(f["leverage"], 2) if "leverage" in f else None,
            }
        out[s] = row
    q = _rank_pct(sm.quality(facts))
    value = sm._mean_of(
        [
            sm._z({s: v["earnings_yield"] for s, v in facts.items() if "earnings_yield" in v}),
            sm._z({s: v["book_yield"] for s, v in facts.items() if "book_yield" in v}),
        ],
        facts,
    )
    vp = _rank_pct(value)
    for s in out:
        out[s]["quality_pct"] = q.get(s)
        out[s]["value_pct"] = vp.get(s)
    return out


# --- the selection history --------------------------------------------------------------------


def history(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or HISTORY
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def record(
    lists: Sequence[Mapping[str, Any]], as_of: str, now: datetime, path: Path | None = None
) -> int:
    """Append each model's picks for `as_of` once. Returns how many were added."""
    p = path or HISTORY
    have = {(str(r["as_of"]), str(r["model"])) for r in history(p)}
    rows = [
        {
            "as_of": as_of,
            "model": item["id"],
            "kind": item["kind"],
            "picks": list(item["picks"]),
            "event_time": as_of,
            "knowledge_time": now.isoformat(),
        }
        for item in lists
        if (as_of, str(item["id"])) not in have and not item.get("error")
    ]
    if rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as handle:
            for r in rows:
                handle.write(json.dumps(r, sort_keys=True) + "\n")
    return len(rows)


def _closes(view: MarketView, symbol: str) -> tuple[list[date], list[float]]:
    rows = view.history.get(symbol) or []
    return [r.day for r in rows], [r.close for r in rows]


def outcome(
    view: MarketView, picks: Sequence[str], as_of: date, hold: int
) -> dict[str, Any] | None:
    """Equal-weight return of `picks` from the session after `as_of` (the engine's fill) over
    `hold` sessions, or to the latest close when fewer have passed, against NIFTYBEES.
    Prices are today's view, adjusted for every action since, so splits do not read as losses."""
    bdays, bclose = _closes(view, BENCHMARK)
    i = bisect_right(bdays, as_of)
    if i >= len(bdays):
        return None
    j = min(i + hold, len(bdays) - 1)
    start, end = bdays[i], bdays[j]
    rets = []
    for s in picks:
        days, close = _closes(view, s)
        a, b = bisect_right(days, start) - 1, bisect_right(days, end) - 1
        if a >= 0 and b >= a and days[a] == start and close[a] > 0:
            rets.append(close[b] / close[a] - 1)
    if not rets:
        return None
    bench = bclose[j] / bclose[i] - 1
    mean = sum(rets) / len(rets)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "sessions": j - i,
        "complete": j - i >= hold,
        "return": round(mean, 4),
        "nifty": round(bench, 4),
        "excess": round(mean - bench, 4),
        "beat_nifty": round(sum(r > bench for r in rets) / len(rets), 3),
        "priced": len(rets),
    }


def track(
    view: MarketView, past: Sequence[Mapping[str, Any]], last: int = 12
) -> dict[str, dict[str, Any]]:
    """Each model's past selections and how they did, newest first, with a summary of complete ones."""
    by: dict[str, list[dict[str, Any]]] = {}
    for r in past:
        if date.fromisoformat(str(r["as_of"])) >= view.as_of:
            continue
        got = outcome(
            view, r["picks"], date.fromisoformat(str(r["as_of"])), HOLD.get(str(r["kind"]), 21)
        )
        if got is not None:
            by.setdefault(str(r["model"]), []).append(
                {"as_of": r["as_of"], "n": len(r["picks"])} | got
            )
    out = {}
    for model, rows in by.items():
        rows.sort(key=lambda x: str(x["as_of"]), reverse=True)
        done = [x for x in rows if x["complete"]]
        out[model] = {
            "selections": rows[:last],
            "complete": len(done),
            "mean_excess": round(sum(x["excess"] for x in done) / len(done), 4) if done else None,
            "beat_nifty_share": round(sum(x["excess"] > 0 for x in done) / len(done), 3)
            if done
            else None,
        }
    return out


def _news_tone() -> dict[str, Any]:
    path = Path("data/derived/stock_news_tone.json")
    if not path.exists():
        return {}
    got = json.loads(path.read_text(encoding="utf-8"))
    return dict(got.get("stocks") or {}) if isinstance(got, dict) else {}


def _models(cfg: Mapping[str, Any]) -> list[tuple[str, str, str, Strategy]]:
    from eulerlab.backtest import screener_models as sm
    from eulerlab.backtest.published import BUILDERS

    out = [(s.id, sm.KIND[s.id], s.title, s.build()) for s in sm.STRATEGIES]
    for e in cfg.get("existing") or []:
        builder = BUILDERS.get(str(e["id"]))
        if builder is not None:
            out.append(
                (str(e["id"]), str(e.get("kind", "long")), str(e.get("title", e["id"])), builder())
            )
    return out


def build(*, now: datetime | None = None, out: Path | None = None) -> dict[str, Any]:
    """Today's lists. Loads the panel (about 1.8 GB in memory)."""
    from eulerlab.backtest import screener_models as sm
    from eulerlab.backtest.india_papers import liquid_universe
    from eulerlab.features.panel import by_symbol, read_panel, trading_days

    now = now or datetime.now(UTC)
    cfg = config()
    rows = read_panel()
    histories = by_symbol(rows)
    day = trading_days(rows)[-1]
    models = _models(cfg)
    longest = max(int(getattr(m, "lookback", 0) or 0) for *_, m in models) + 5
    view = adjusted_view(histories, day, longest, _events())
    del rows
    runs, bench = backtests(list(cfg.get("summaries") or []))
    names = liquid_universe(view)
    table = reasons(view, names)
    tone = _news_tone()
    lists = []
    for mid, kind, title, strategy in models:
        lookback = int(getattr(strategy, "lookback", 0) or 0)
        narrowed = MarketView(
            as_of=view.as_of,
            history={
                s: list(h[-lookback:]) if lookback else list(h) for s, h in view.history.items()
            },
        )
        try:
            longs, _ = decide(strategy, narrowed)
            error = ""
        except Exception as exc:  # one model failing must not empty the page
            longs, error = {}, f"{type(exc).__name__}: {str(exc)[:120]}"
        picks = sorted(longs, key=lambda s: (-longs[s], s))
        for s in picks:
            table.setdefault(s, {}).setdefault("models", []).append(mid)
        run = runs.get(mid, {})
        lists.append(
            {
                "id": mid,
                "kind": kind,
                "title": title,
                "new": mid in sm.BY_ID,
                "picks": picks,
                "error": error,
                "backtest": {
                    k: run.get(k)
                    for k in (
                        "sharpe",
                        "total_return",
                        "max_drawdown",
                        "fills",
                        "costs",
                        "window",
                        "benchmark",
                    )
                },
                "gate": "not promoted: screening backtest only; the gate decides (`make validate`, `make gate`)",
            }
        )
    added = record(lists, day.isoformat(), now)
    tracked = track(view, history())
    for item in lists:
        item["track"] = tracked.get(str(item["id"])) or {"selections": [], "complete": 0}
    for s, row in table.items():
        row.setdefault("models", [])
        t = tone.get(s)
        if t:
            row["news_tone"] = {"mean": t.get("mean"), "n": t.get("n")}
    result = {
        "as_of": day.isoformat(),
        "built": now.isoformat(),
        "universe": "the 250 most-traded stocks by median turnover over 60 sessions, as of today",
        "lists": lists,
        "stocks": dict(sorted(table.items())),
        "benchmark": bench,
        "history": {
            "recorded_today": added,
            "since": min((str(r["as_of"]) for r in history()), default=""),
        },
        "caveats": [
            "Past selections are recorded from the day this page was built and measured from the next "
            "session's close over the model's own holding period (swing 5 sessions, long-term 21), "
            "against NIFTYBEES, before costs.",
            "A list is what a model would hold today, not advice. No model has passed the gate.",
            "Backtests are screening runs (Tier B, after Indian costs, 2016-2026): no trial was spent, "
            "so they have not been through the noise bar.",
            "Fundamentals count from 90 days after each year end (A-107) and carry later restatements; "
            "only companies listed in 2026 have them, so fundamental models pick survivors.",
            "The existing five are all momentum: they are close to one bet (HISTORY #44).",
        ],
    }
    p = out or OUT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, sort_keys=True, default=_jsonable), encoding="utf-8")
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def build_fundamentals() -> dict[str, int]:
    from eulerlab.features.panel import read_panel
    from eulerlab.fundamentals import annual

    return annual.build(isin_map(read_panel()))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="screener")
    parser.add_argument("what", choices=("build", "build-fundamentals"))
    args = parser.parse_args(argv)
    if args.what == "build-fundamentals":
        got = build_fundamentals()
        print(
            f"fundamentals-annual: {got['companies']} companies, {got['years']} years; "
            f"{got['read']} snapshots read, {got['no_isin']} tickers without an ISIN, {got['failed']} unreadable"
        )
        return 0
    result = build()
    for item in result["lists"]:
        bt = item["backtest"]
        print(
            f"{item['kind']:5} {item['id']:34} {len(item['picks']):3} picks"
            f"  sharpe {bt.get('sharpe')}  {item['error']}"
        )
    print(f"screener: {len(result['stocks'])} stocks, as of {result['as_of']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
