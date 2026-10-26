"""Where a backtest's return came from: holdings, sectors, years and the market.

A Sharpe and a total return say how much; they do not say whether it came from
a broad edge or from a handful of stocks, one sector, one year or simply being
long a rising market. Weinstein Stage 2 (research 113) made the point: +1,456%
in ten years, half of it from five stocks and a quarter from one. Four views
answer the four questions, each computed from what a stored report already
holds, so every past report and every paper deployment gets them without a
re-run.

- **Holdings.** Each instrument's contribution in rupees (`reports.Constituent`,
  which reconciles to the equity change), top-winner shares of gross positive
  profit, how many winners make half and four-fifths of gross gains, and the
  return with the top five removed. Net profit is reported separately.
- **Sectors.** Contribution summed by NSE sector and industry (the company
  digest's classification, as it stands today: A-061).
- **Years.** Closed trades' net profit by exit year, open positions in the
  final year, and each year's largest contributor.
- **Market.** Daily strategy returns regressed on the market ETF for that run:
  NIFTYBEES for Indian equities and SPY (the S&P 500 ETF) for US equities.

Brinson attribution, the textbook split into allocation and selection, needs a
benchmark's sector weights each period; none is held, so contribution analysis
stands in for it (research 114).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast

TRADING_DAYS = 252
TOP = (1, 5, 10)


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def holdings(
    constituents: Sequence[Mapping[str, Any]], starting_cash: float, years: float
) -> dict[str, Any]:
    ranked = sorted(constituents, key=lambda c: -float(c["contribution"]))
    net = sum(float(c["contribution"]) for c in ranked)
    gross_profit = sum(max(0.0, float(c["contribution"])) for c in ranked)
    winners = [c for c in ranked if float(c["contribution"]) > 0]

    def winners_for(fraction: float) -> int | None:
        if gross_profit <= 0:
            return None
        running = 0.0
        winners_ranked = [c for c in ranked if float(c["contribution"]) > 0]
        for count, c in enumerate(winners_ranked, start=1):
            running += float(c["contribution"])
            if running >= fraction * gross_profit:
                return count
        return None

    def without(n: int) -> dict[str, float | None]:
        # Removing top contributors means removing winners only. If there are
        # fewer than n winners, do not remove losing positions as a side effect.
        rest = net - sum(float(c["contribution"]) for c in winners[:n])
        total = rest / starting_cash if starting_cash > 0 else None
        cagr = (
            (1 + total) ** (1 / years) - 1
            if total is not None and total > -1 and years > 0
            else None
        )
        return {"total_return": _round(total), "annualised": _round(cagr)}

    return {
        "net_profit": round(net, 2),
        "names": len(ranked),
        "winners": len(winners),
        "losers": len(ranked) - len(winners),
        "share_of_profit": {
            f"top_{n}": _round(sum(float(c["contribution"]) for c in ranked[:n]) / net)
            if net > 0
            else None
            for n in TOP
        },
        "share_of_gross_profit": {
            f"top_{n}": _round(
                sum(max(0.0, float(c["contribution"])) for c in ranked[:n]) / gross_profit
            )
            if gross_profit > 0
            else None
            for n in TOP
        },
        "names_for_half": winners_for(0.5),
        "names_for_four_fifths": winners_for(0.8),
        "without_top_1": without(1),
        "without_top_5": without(5),
        "best": [
            {"symbol": c["symbol"], "contribution": round(float(c["contribution"]), 2)}
            for c in ranked[:10]
        ],
        "worst": [
            {"symbol": c["symbol"], "contribution": round(float(c["contribution"]), 2)}
            for c in ranked[-5:][::-1]
            if float(c["contribution"]) < 0
        ],
    }


def sectors(
    constituents: Sequence[Mapping[str, Any]], classify: Mapping[str, tuple[str, str]]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    net = sum(float(c["contribution"]) for c in constituents)
    for level, index in (("sector", 0), ("industry", 1)):
        groups: dict[str, list[float]] = defaultdict(list)
        for c in constituents:
            label = (classify.get(str(c["symbol"])) or ("Unclassified", "Unclassified"))[
                index
            ] or "Unclassified"
            groups[label].append(float(c["contribution"]))
        out[level] = sorted(
            (
                {
                    "name": name,
                    "contribution": round(sum(values), 2),
                    "share": _round(sum(values) / net) if net else None,
                    "names": len(values),
                    "winners": sum(1 for v in values if v > 0),
                }
                for name, values in groups.items()
            ),
            key=lambda row: -row["contribution"],
        )
    return out


def by_year(
    trades: Sequence[Mapping[str, Any]],
    constituents: Sequence[Mapping[str, Any]],
    equity: Mapping[str, Sequence[Any]],
    starting_cash: float,
) -> list[dict[str, Any]]:
    """Net profit of trades closed each year, open positions counted in the last."""
    days, values = list(equity.get("days") or []), list(equity.get("values") or [])
    if not days:
        return []
    last_year = str(days[-1])[:4]
    per_year: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in trades:
        if t.get("open"):
            continue
        year = str(t.get("exit_day") or "")[:4]
        if year:
            per_year[year][str(t["symbol"])] += float(t.get("net") or 0.0)
    # Open positions, unrealised: their value now against what the open lots cost.
    open_cost: dict[str, float] = defaultdict(float)
    for t in trades:
        if t.get("open"):
            open_cost[str(t["symbol"])] += float(t.get("entry_price") or 0.0) * float(
                t.get("quantity") or 0.0
            )
    for c in constituents:
        symbol = str(c["symbol"])
        if int(c.get("open_qty") or 0) and symbol in open_cost:
            per_year[last_year][symbol] += float(c["open_value"]) - open_cost[symbol]

    year_end: dict[str, float] = {}
    for d, v in zip(days, values, strict=True):
        year_end[str(d)[:4]] = float(v)
    previous = starting_cash
    rows = []
    for year in sorted(set(year_end) | set(per_year)):
        symbols = per_year.get(year, {})
        top = max(symbols.items(), key=lambda kv: kv[1], default=None)
        end = year_end.get(year, previous)
        rows.append(
            {
                "year": year,
                "return": _round(end / previous - 1.0) if previous > 0 else None,
                "trading_profit": round(sum(symbols.values()), 2),
                "top_symbol": top[0] if top else None,
                "top_profit": round(top[1], 2) if top else None,
                "top_share": _round(top[1] / sum(v for v in symbols.values() if v > 0))
                if top and any(v > 0 for v in symbols.values())
                else None,
            }
        )
        previous = end
    return rows


def market(
    equity: Mapping[str, Sequence[Any]],
    index: Mapping[date, float],
    index_name: str = "NIFTYBEES",
) -> dict[str, Any] | None:
    """Daily returns on the index's: beta, annual alpha, R^2, what beta alone earned."""
    days = [date.fromisoformat(str(d)) for d in equity.get("days") or []]
    values = [float(v) for v in equity.get("values") or []]
    pairs = []
    matched_start: date | None = None
    matched_end: date | None = None
    for i in range(1, len(days)):
        a, b = index.get(days[i - 1]), index.get(days[i])
        if a and b and values[i - 1] > 0:
            pairs.append((values[i] / values[i - 1] - 1.0, b / a - 1.0))
            matched_start = matched_start or days[i - 1]
            matched_end = days[i]
    if len(pairs) < 2:
        return None
    s = [p[0] for p in pairs]
    m = [p[1] for p in pairs]
    mean_s, mean_m = statistics.fmean(s), statistics.fmean(m)
    var_m = statistics.pvariance(m)
    var_s = statistics.pvariance(s)
    cov = sum((x - mean_s) * (y - mean_m) for x, y in pairs) / len(pairs)
    enough_data = len(pairs) >= 60 and var_m > 0 and var_s > 0
    beta = cov / var_m if enough_data else None
    alpha_daily = mean_s - beta * mean_m if beta is not None else None
    r2 = cov * cov / (var_m * var_s) if enough_data else None
    return {
        "beta": _round(beta, 3),
        "alpha_annual": _round(alpha_daily * TRADING_DAYS) if alpha_daily is not None else None,
        "r_squared": _round(r2, 3),
        "correlation": _round(math.copysign(math.sqrt(r2), cov), 3) if r2 is not None else None,
        "strategy_total": _round(math.prod(1.0 + x for x in s) - 1.0),
        "market_total": _round(math.prod(1.0 + x for x in m) - 1.0),
        "from": matched_start.isoformat() if matched_start else "",
        "through": matched_end.isoformat() if matched_end else "",
        "strategy_mean_annual": _round(mean_s * TRADING_DAYS) if enough_data else None,
        "market_mean_annual": _round(mean_m * TRADING_DAYS) if enough_data else None,
        "from_market_annual": _round(beta * mean_m * TRADING_DAYS) if beta is not None else None,
        "days": len(pairs),
        "index": index_name,
    }


_CACHE: dict[str, tuple[float, Any]] = {}


def _cached[T](name: str, path: Path, build: Callable[[], T]) -> T:
    """`build()`, kept until the file it reads changes (both take about a second)."""
    stamp = path.stat().st_mtime if path.exists() else 0.0
    found = _CACHE.get(name)
    if found is None or found[0] != stamp:
        found = (stamp, build())
        _CACHE[name] = found
    return cast(T, found[1])


def _classification() -> dict[str, tuple[str, str]]:
    from eulerlab.features import company

    return _cached(
        "sectors",
        company.DIGEST_PATH,
        lambda: {s: (c.sector, c.industry) for s, c in company.load_digest().items()},
    )


def _nifty() -> dict[date, float]:
    from eulerlab.benchmark import _nifty_closes
    from eulerlab.features.panel import PANEL_PATH

    return _cached("niftybees", PANEL_PATH, lambda: dict(_nifty_closes()))


def _spy() -> dict[date, float]:
    from eulerlab.features import us_panel

    return _cached(
        "spy",
        us_panel.PANEL_PATH,
        lambda: {row.day: row.close for row in us_panel.read() if row.symbol == "SPY"},
    )


def analyse(
    report: Mapping[str, Any],
    *,
    classify: Callable[[], Mapping[str, tuple[str, str]]] = _classification,
    index: Callable[[], Mapping[date, float]] = _nifty,
    us_index: Callable[[], Mapping[date, float]] = _spy,
) -> dict[str, Any]:
    """All four views for one stored report (a backtest's, or a deployment's)."""
    constituents = report.get("constituents") or []
    equity = report.get("equity") or {}
    starting = float(report.get("starting_cash") or 0.0)
    days = equity.get("days") or []
    years = (
        (date.fromisoformat(str(days[-1])) - date.fromisoformat(str(days[0]))).days / 365.25
        if len(days) > 1
        else 0.0
    )
    try:
        mapping = classify()
    except Exception:  # a missing digest leaves sectors out, never the report
        mapping = {}
    asset_class = str(report.get("asset_class") or "equity")
    benchmark_name = {"equity": "NIFTYBEES", "us": "S&P 500 (SPY)"}.get(asset_class)
    try:
        levels = (us_index if asset_class == "us" else index)() if benchmark_name else {}
    except Exception:
        levels = {}
    return {
        "holdings": holdings(constituents, starting, years),
        "sectors": sectors(constituents, mapping) if mapping else None,
        "years": by_year(report.get("trades") or [], constituents, equity, starting),
        "market": market(equity, levels, benchmark_name) if levels and benchmark_name else None,
        "note": (
            "Contribution analysis: each holding's rupee profit, summed. Sectors are NSE's "
            "classification as it stands today. Market comparison: daily returns regressed "
            "on NIFTYBEES (India) or SPY/S&P 500 (US), when prices cover the run."
        ),
    }
