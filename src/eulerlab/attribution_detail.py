"""Detailed attribution: Brinson by sector, house factors, risk, drawdowns, trades, capacity.

Research 115. `attribution.analyse` (research 114) reads only what a report
stores. This module rebuilds the daily book from the report's fills and the
panel's adjusted closes, as pyfolio does, checks the rebuild against the stored
equity curve, and from the book answers what the platforms answer:

- **Brinson-Fachler by sector**, each month against an equal-weight benchmark of
  the point-in-time 250 most-traded stocks, linked over the run with Carino's
  factors so allocation + selection + interaction add up to the active return.
- **Four house factors** built from the panel (market, size by turnover,
  momentum 12-1, low volatility), monthly long-short within the 500
  most-traded; the run's monthly returns regressed on them.
- **Euler risk contributions** of the final book by holding and sector.
- **Time:** rolling twelve-month beta and alpha, the best and worst months and
  the three deepest drawdowns with the holdings that drove each.
- **Trades:** round trips by holding period and sector; profit from the best 1%.
- **Capacity:** each entry against the stock's median daily turnover.

Months are calendar months; "month-end" is each symbol's last trading day in
it. The monthly base for the benchmark and factors is built once from the
whole panel and cached on disk (`MONTHLY_PATH`), rebuilt when the panel changes.
"""

from __future__ import annotations

import bisect
import json
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from itertools import pairwise
from typing import Any

import numpy as np

from eulerlab.features.panel import PANEL_PATH, PanelRow
from eulerlab.paths import data_path

MONTHLY_PATH = data_path("derived/attribution_monthly.json")
BENCHMARK_TOP = 250
FACTOR_TOP = 500
PARTICIPATION = 0.2
"""Share of a day's turnover one order may take, for the capacity estimate."""
REBUILD_TOLERANCE = 0.02
"""Largest relative gap between the rebuilt and stored equity for the
holdings-based views to be shown."""


def _r(value: float | None, digits: int = 6) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


# --- the monthly base: every stock, every month ----------------------------------


def _panel_rows(asset_class: str = "equity") -> list[PanelRow]:
    if asset_class == "us":
        from eulerlab.features.alt_panel import us_daily

        return us_daily()
    from eulerlab.api.panels import PANEL

    return PANEL.rows()


def build_monthly(rows: Sequence[PanelRow]) -> dict[str, Any]:
    """Month-end adjusted close and mean daily turnover, per symbol per month."""
    from eulerlab.backtest.vector import build_adjusted_index

    last: dict[tuple[str, str], PanelRow] = {}
    turnover: dict[tuple[str, str], list[float]] = defaultdict(list)
    funds: set[str] = set()
    for row in rows:
        month = row.day.isoformat()[:7]
        key = (row.symbol, month)
        if key not in last or row.day > last[key].day:
            last[key] = row
        turnover[key].append(row.turnover)
        if row.isin.startswith("INF") or row.symbol.upper() in {"NIFTYBEES", "SPY"}:
            funds.add(row.symbol)
    adjusted = build_adjusted_index(list(last.values()))
    months = sorted({m for _, m in last})
    position = {m: i for i, m in enumerate(months)}
    symbols: dict[str, dict[str, list[float | None]]] = {}
    for (symbol, month), row in last.items():
        entry = symbols.setdefault(
            symbol, {"close": [None] * len(months), "turnover": [None] * len(months)}
        )
        i = position[month]
        entry["close"][i] = adjusted.get(symbol, {}).get(row.day)
        values = turnover[(symbol, month)]
        entry["turnover"][i] = sum(values) / len(values) if values else None
    return {"months": months, "funds": sorted(funds), "symbols": symbols}


def monthly_base(asset_class: str = "equity") -> dict[str, Any]:
    if asset_class == "us":
        from eulerlab.features import us_panel

        source_path = us_panel.PANEL_PATH
        cache_path = MONTHLY_PATH.with_name("attribution_monthly_us.json")
    else:
        source_path = PANEL_PATH
        cache_path = MONTHLY_PATH
    stamp = source_path.stat().st_mtime if source_path.exists() else 0.0
    if cache_path.exists():
        cached: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("panel_stamp") == stamp:
            return cached
    base = build_monthly(_panel_rows(asset_class))
    base["panel_stamp"] = stamp
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")
    return base


def _ranked(base: Mapping[str, Any], i: int, top: int) -> list[str]:
    """The `top` stocks (funds out) by mean daily turnover in month i, with a close in i and i+1."""
    funds = set(base["funds"])
    found = []
    for symbol, s in base["symbols"].items():
        if symbol in funds:
            continue
        t, c = s["turnover"][i], s["close"]
        if t and i + 1 < len(c) and c[i] and c[i + 1]:
            found.append((t, symbol))
    found.sort(key=lambda x: (-x[0], x[1]))
    return [s for _, s in found[:top]]


def _next_return(base: Mapping[str, Any], symbol: str, i: int) -> float:
    c = base["symbols"][symbol]["close"]
    return float(c[i + 1]) / float(c[i]) - 1.0


def benchmark_by_month(
    base: Mapping[str, Any], classify: Mapping[str, tuple[str, str]]
) -> dict[str, dict[str, Any]]:
    """Month -> {sector: (weight, return)} of the equal-weight top 250 over the next month."""
    out: dict[str, dict[str, Any]] = {}
    for i, month in enumerate(base["months"][:-1]):
        names = _ranked(base, i, BENCHMARK_TOP)
        if len(names) < 50:
            continue
        groups: dict[str, list[float]] = defaultdict(list)
        for s in names:
            groups[(classify.get(s) or ("Unclassified", ""))[0] or "Unclassified"].append(
                _next_return(base, s, i)
            )
        out[month] = {
            sector: (len(v) / len(names), statistics.fmean(v)) for sector, v in groups.items()
        }
    return out


def house_factors(base: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Month t -> factor returns over month t+1: size, momentum, low volatility."""
    out: dict[str, dict[str, float]] = {}
    months = base["months"]
    for i in range(12, len(months) - 1):
        names = _ranked(base, i, FACTOR_TOP)
        if len(names) < 100:
            continue
        rows = []
        for s in names:
            c = base["symbols"][s]["close"]
            window = c[i - 12 : i + 1]
            if any(v is None or v <= 0 for v in window):
                continue
            monthly = [b / a - 1.0 for a, b in pairwise(window)]
            rows.append(
                {
                    "symbol": s,
                    "next": _next_return(base, s, i),
                    "turnover": base["symbols"][s]["turnover"][i],
                    "momentum": window[-2] / window[0] - 1.0,
                    "vol": statistics.pstdev(monthly),
                }
            )
        if len(rows) < 100:
            continue

        def spread(
            key: str, frac: float, high_minus_low: bool, rows: list[dict[str, Any]] = rows
        ) -> float:
            ordered = sorted(rows, key=lambda r: (r[key], r["symbol"]))
            n = max(1, int(len(ordered) * frac))
            low = statistics.fmean(r["next"] for r in ordered[:n])
            high = statistics.fmean(r["next"] for r in ordered[-n:])
            return high - low if high_minus_low else low - high

        out[months[i]] = {
            "size": spread("turnover", 0.5, high_minus_low=False),
            "momentum": spread("momentum", 0.3, high_minus_low=True),
            "low_volatility": spread("vol", 0.3, high_minus_low=False),
        }
    return out


# --- the run's own book, rebuilt ---------------------------------------------------


def rebuild(report: Mapping[str, Any], rows: Sequence[PanelRow]) -> dict[str, Any]:
    """Daily shares and marks from the fills; checked against the stored equity."""
    from eulerlab.backtest.vector import build_adjusted_index

    orders = report.get("orders") or []
    symbols = {str(o["symbol"]) for o in orders}
    mine = [r for r in rows if r.symbol in symbols]
    prices = build_adjusted_index(mine)
    turnover: dict[str, dict[date, float]] = defaultdict(dict)
    for r in mine:
        turnover[r.symbol][r.day] = r.turnover
    days = [date.fromisoformat(str(d)) for d in (report.get("equity") or {}).get("days") or []]
    stored = [float(v) for v in (report.get("equity") or {}).get("values") or []]
    by_day: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
    for o in orders:
        by_day[date.fromisoformat(str(o["day"]))].append(o)

    cash = float(report.get("starting_cash") or 0.0)
    shares: dict[str, float] = defaultdict(float)
    last_price: dict[str, float] = {}
    book: list[dict[str, float]] = []
    rebuilt: list[float] = []
    for d in days:
        for o in by_day.get(d, []):
            sign = 1.0 if str(o["side"]).lower().endswith("buy") else -1.0
            qty, px = float(o["quantity"]), float(o["price"])
            shares[str(o["symbol"])] += sign * qty
            cash -= sign * qty * px + float(o.get("cost") or 0.0)
            last_price[str(o["symbol"])] = px
        values: dict[str, float] = {}
        for s, q in shares.items():
            if abs(q) < 1e-9:
                continue
            p = prices.get(s, {}).get(d)
            if p is not None:
                last_price[s] = p
            values[s] = q * last_price.get(s, 0.0)
        book.append(values)
        rebuilt.append(cash + sum(values.values()))
    gaps = [abs(a - b) / b for a, b in zip(rebuilt, stored, strict=False) if b > 0]
    return {
        "days": days,
        "book": book,
        "equity": stored,
        "rebuilt": rebuilt,
        "max_gap": max(gaps) if gaps else None,
        "prices": prices,
        "turnover": turnover,
    }


def _month_ends(days: Sequence[date]) -> list[int]:
    """Index of the last day of each calendar month."""
    return [i for i in range(len(days)) if i + 1 == len(days) or days[i + 1].month != days[i].month]


def _price_at(prices: Mapping[date, float], d: date) -> float | None:
    if d in prices:
        return prices[d]
    keys = sorted(prices)
    j = bisect.bisect_right(keys, d) - 1
    return prices[keys[j]] if j >= 0 else None


def brinson(
    rebuilt: Mapping[str, Any],
    bench: Mapping[str, Mapping[str, tuple[float, float]]],
    classify: Mapping[str, tuple[str, str]],
) -> dict[str, Any] | None:
    """Brinson-Fachler by sector each month, Carino-linked over the run."""
    days, book, equity, prices = (
        rebuilt["days"],
        rebuilt["book"],
        rebuilt["equity"],
        rebuilt["prices"],
    )
    ends = _month_ends(days)
    periods = []
    for a, b in pairwise(ends):
        month = days[a].isoformat()[:7]
        if month not in bench or equity[a] <= 0:
            continue
        start_values = book[a]
        weights: dict[str, float] = defaultdict(float)
        sector_return_num: dict[str, float] = defaultdict(float)
        for s, v in start_values.items():
            sector = (classify.get(s) or ("Unclassified", ""))[0] or "Unclassified"
            p0, p1 = _price_at(prices.get(s, {}), days[a]), _price_at(prices.get(s, {}), days[b])
            if not p0 or p1 is None:
                continue
            weights[sector] += v / equity[a]
            sector_return_num[sector] += v / equity[a] * (p1 / p0 - 1.0)
        invested = sum(weights.values())
        weights["Cash"] += 1.0 - invested
        rp_i = {k: (sector_return_num[k] / w if w else 0.0) for k, w in weights.items()}
        rp_i["Cash"] = 0.0
        b_i = dict(bench[month])
        rb = sum(w * r for w, r in b_i.values())
        rp_bh = sum(weights[k] * rp_i[k] for k in weights)
        actual = equity[b] / equity[a] - 1.0
        effects: dict[str, dict[str, float]] = {}
        for sector in set(weights) | set(b_i):
            wp, wb = weights.get(sector, 0.0), b_i.get(sector, (0.0, rb))[0]
            r_b = b_i[sector][1] if sector in b_i else (0.0 if sector == "Cash" else rb)
            r_p = rp_i.get(sector, r_b) if wp > 0 else r_b
            effects[sector] = {
                "allocation": (wp - wb) * (r_b - rb),
                "selection": wb * (r_p - r_b),
                "interaction": (wp - wb) * (r_p - r_b),
                "weight": wp,
                "benchmark_weight": wb,
            }
        periods.append(
            {"month": month, "rp": rp_bh, "rb": rb, "actual": actual, "effects": effects}
        )
    if len(periods) < 6:
        return None

    def link(r: float) -> float:
        return math.log1p(r)

    rp_total = math.prod(1 + p["rp"] for p in periods) - 1
    rb_total = math.prod(1 + p["rb"] for p in periods) - 1
    actual_total = math.prod(1 + p["actual"] for p in periods) - 1
    big_k = (
        (link(rp_total) - link(rb_total)) / (rp_total - rb_total)
        if rp_total != rb_total
        else 1 / (1 + rp_total)
    )
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    weight_sum: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for p in periods:
        diff = p["rp"] - p["rb"]
        k = (link(p["rp"]) - link(p["rb"])) / diff if abs(diff) > 1e-12 else 1 / (1 + p["rp"])
        for sector, e in p["effects"].items():
            for name in ("allocation", "selection", "interaction"):
                totals[sector][name] += e[name] * k / big_k
            weight_sum[sector][0] += e["weight"]
            weight_sum[sector][1] += e["benchmark_weight"]
    n = len(periods)
    rows: list[dict[str, Any]] = sorted(
        (
            {
                "sector": sector,
                "allocation": _r(v["allocation"]),
                "selection": _r(v["selection"]),
                "interaction": _r(v["interaction"]),
                "total": _r(v["allocation"] + v["selection"] + v["interaction"]),
                "average_weight": _r(weight_sum[sector][0] / n, 4),
                "benchmark_weight": _r(weight_sum[sector][1] / n, 4),
            }
            for sector, v in totals.items()
        ),
        key=lambda r: -(r["total"] or 0.0),
    )
    years = n / 12
    return {
        "months": n,
        "benchmark": "equal-weight point-in-time 250 most-traded",
        "portfolio_buy_hold": _r(rp_total),
        "benchmark_total": _r(rb_total),
        "benchmark_annual": _r((1 + rb_total) ** (1 / years) - 1) if years > 0 else None,
        "actual_total": _r(actual_total),
        "active": _r(rp_total - rb_total),
        "allocation": _r(sum(r["allocation"] or 0.0 for r in rows)),
        "selection": _r(sum(r["selection"] or 0.0 for r in rows)),
        "interaction": _r(sum(r["interaction"] or 0.0 for r in rows)),
        "trading": _r(actual_total - rp_total),
        "sectors": rows,
    }


def _ols(y: Sequence[float], xs: Mapping[str, Sequence[float]]) -> dict[str, Any] | None:
    names = list(xs)
    if len(y) < len(names) + 12:
        return None
    x = np.column_stack([np.ones(len(y))] + [np.asarray(xs[k], dtype=float) for k in names])
    yv = np.asarray(y, dtype=float)
    coef, *_ = np.linalg.lstsq(x, yv, rcond=None)
    resid = yv - x @ coef
    # Monthly observations can be heteroskedastic and serially correlated.
    # Use a Newey-West HAC covariance with three monthly lags for the reported
    # t-statistics, rather than the optimistic iid OLS standard errors.
    scores = x * resid[:, None]
    meat = scores.T @ scores
    lags = min(3, len(y) - 1)
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)
    bread = np.linalg.pinv(x.T @ x)
    cov = bread @ meat @ bread
    dof = len(y) - x.shape[1]
    cov *= len(y) / max(1, dof)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r_squared = 1 - float(resid @ resid) / ss_tot if ss_tot > 0 else None
    adjusted_r_squared = (
        1 - (1 - r_squared) * (len(y) - 1) / dof if r_squared is not None and dof > 0 else None
    )
    return {
        "alpha_monthly": float(coef[0]),
        "alpha_t": float(coef[0] / se[0]) if se[0] > 0 else None,
        "betas": {k: float(coef[i + 1]) for i, k in enumerate(names)},
        "t": {
            k: float(coef[i + 1] / se[i + 1]) if se[i + 1] > 0 else None
            for i, k in enumerate(names)
        },
        "r_squared": r_squared,
        "adjusted_r_squared": adjusted_r_squared,
        "months": len(y),
        "residuals": [float(v) for v in resid],
    }


def factors(
    rebuilt: Mapping[str, Any],
    house: Mapping[str, Mapping[str, float]],
    market: Mapping[date, float],
    *,
    market_label: str = "NIFTYBEES",
    risk_free: Mapping[str, float] | None = None,
    model_name: str = "Custom NSE four-factor model",
    source_url: str | None = None,
    factor_description: str | None = None,
) -> dict[str, Any] | None:
    """Fit monthly strategy returns on the supplied market and style-return series."""
    days, equity = rebuilt["days"], rebuilt["equity"]
    ends = _month_ends(days)
    market_days = sorted(market)
    y, strategy_returns, rf_returns, cols = [], [], [], defaultdict(list)
    matched_months: list[str] = []
    for a, b in pairwise(ends):
        return_month = days[b].isoformat()[:7]
        factor_month = return_month if risk_free is not None else days[a].isoformat()[:7]
        if factor_month not in house or equity[a] <= 0:
            continue
        if risk_free is not None and return_month not in risk_free:
            continue
        if "market" in house[factor_month]:
            market_return = house[factor_month]["market"]
        else:
            m0, m1 = _price_at(market, days[a]), _price_at(market, days[b])
            if not m0 or m1 is None or not market_days:
                continue
            market_return = m1 / m0 - 1.0
        strategy_return = equity[b] / equity[a] - 1.0
        rf = risk_free[return_month] if risk_free is not None else 0.0
        strategy_returns.append(strategy_return)
        rf_returns.append(rf)
        y.append(strategy_return - rf)
        cols["market"].append(market_return)
        matched_months.append(return_month)
        for k, v in house[factor_month].items():
            if k != "market":
                cols[k].append(v)
    fit = _ols(y, cols)
    if fit is None:
        return None
    means = {k: statistics.fmean(v) for k, v in cols.items()}
    contributions = {k: float(fit["betas"][k] * means[k] * 12) for k in cols}
    alpha_annual = float(fit["alpha_monthly"] * 12)
    rf_annual = statistics.fmean(rf_returns) * 12 if risk_free is not None and rf_returns else None
    yearly_values: dict[str, list[int]] = defaultdict(list)
    for i, month in enumerate(matched_months):
        yearly_values[month[:4]].append(i)
    yearly = []
    for year, indexes in sorted(yearly_values.items()):
        by_factor = {
            k: _r(fit["betas"][k] * statistics.fmean(cols[k][i] for i in indexes) * 12)
            for k in cols
        }
        period_residual = statistics.fmean(fit["residuals"][i] for i in indexes) * 12
        risk_free_annual = statistics.fmean(rf_returns[i] for i in indexes) * 12
        if risk_free is not None:
            by_factor["risk_free"] = _r(risk_free_annual)
        yearly.append(
            {
                "year": int(year),
                "months": len(indexes),
                "strategy_annual": _r(statistics.fmean(strategy_returns[i] for i in indexes) * 12),
                "contributions": {**by_factor, "residual": _r(period_residual)},
            }
        )
    period_from = matched_months[0] if matched_months else None
    period_through = matched_months[-1] if matched_months else None
    return {
        "months": fit["months"],
        "period_from": period_from,
        "period_through": period_through,
        "market_label": market_label,
        "model_name": model_name,
        "source_url": source_url,
        "r_squared": _r(fit["r_squared"], 3),
        "adjusted_r_squared": _r(fit["adjusted_r_squared"], 3),
        "alpha_annual": _r(alpha_annual),
        "alpha_t": _r(fit["alpha_t"], 2),
        "strategy_annual": _r(statistics.fmean(strategy_returns) * 12),
        "risk_free_annual": _r(rf_annual),
        "yearly": yearly,
        "inference": "Newey-West HAC standard errors, 3 monthly lags",
        "exposures": {
            k: {
                "beta": _r(fit["betas"][k], 3),
                "t": _r(fit["t"][k], 2),
                "factor_annual": _r(means[k] * 12),
                "contribution_annual": contributions[k],
            }
            for k in cols
        },
        "factors": factor_description
        or (
            f"market = {market_label}; size = low minus high turnover; momentum = 12-1 top 30% minus bottom 30%; "
            "low volatility = low minus high 12-month volatility; all within the 500 most-traded, monthly, gross of costs"
        ),
    }


def rolling(
    rebuilt: Mapping[str, Any], nifty: Mapping[date, float], window: int = 12
) -> list[dict[str, Any]]:
    days, equity = rebuilt["days"], rebuilt["equity"]
    ends = _month_ends(days)
    pairs = []
    for a, b in pairwise(ends):
        m0, m1 = _price_at(nifty, days[a]), _price_at(nifty, days[b])
        if m0 and m1 is not None and equity[a] > 0:
            pairs.append((days[b].isoformat()[:7], equity[b] / equity[a] - 1.0, m1 / m0 - 1.0))
    out = []
    for i in range(window, len(pairs) + 1):
        chunk = pairs[i - window : i]
        s, m = [c[1] for c in chunk], [c[2] for c in chunk]
        var_m = statistics.pvariance(m)
        if var_m <= 0:
            continue
        beta = sum(
            (a - statistics.fmean(s)) * (b - statistics.fmean(m)) for a, b in zip(s, m, strict=True)
        ) / (len(s) * var_m)
        alpha = (statistics.fmean(s) - beta * statistics.fmean(m)) * 12
        out.append({"month": chunk[-1][0], "beta": _r(beta, 3), "alpha_annual": _r(alpha)})
    return out


def _pnl(rebuilt: Mapping[str, Any], start: int, end: int) -> dict[str, float]:
    """Each holding's mark-to-market profit between two day indexes."""
    days, book, prices = rebuilt["days"], rebuilt["book"], rebuilt["prices"]
    out: dict[str, float] = defaultdict(float)
    for i in range(max(start, 1), end + 1):
        for s, v in book[i - 1].items():
            p0, p1 = (
                _price_at(prices.get(s, {}), days[i - 1]),
                _price_at(prices.get(s, {}), days[i]),
            )
            if p0 and p1 is not None:
                out[s] += v * (p1 / p0 - 1.0)
    return out


def drawdowns(rebuilt: Mapping[str, Any], top: int = 3) -> list[dict[str, Any]]:
    days, equity = rebuilt["days"], rebuilt["equity"]
    episodes: list[tuple[int, int, int | None]] = []
    peak_i, trough_i, in_dd = 0, 0, False
    for i, v in enumerate(equity):
        if v >= equity[peak_i]:
            if in_dd:
                episodes.append((peak_i, trough_i, i))
                in_dd = False
            peak_i = trough_i = i
        else:
            in_dd = True
            if v < equity[trough_i]:
                trough_i = i
    if in_dd:
        episodes.append((peak_i, trough_i, None))
    episodes.sort(key=lambda e: equity[e[1]] / equity[e[0]])
    out = []
    for p, t, r in episodes[:top]:
        losses = _pnl(rebuilt, p + 1, t)
        total = sum(losses.values())
        worst = sorted(losses.items(), key=lambda kv: kv[1])[:5]
        out.append(
            {
                "peak": days[p].isoformat(),
                "trough": days[t].isoformat(),
                "recovered": days[r].isoformat() if r is not None else None,
                "depth": _r(equity[t] / equity[p] - 1.0),
                "days_to_trough": (days[t] - days[p]).days,
                "worst": [
                    {"symbol": s, "loss": round(v, 2), "share": _r(v / total) if total else None}
                    for s, v in worst
                ],
            }
        )
    return out


def months(rebuilt: Mapping[str, Any], top: int = 3) -> dict[str, list[dict[str, Any]]]:
    days, equity = rebuilt["days"], rebuilt["equity"]
    ends = _month_ends(days)
    rows = []
    for a, b in pairwise(ends):
        if equity[a] <= 0:
            continue
        pnl = _pnl(rebuilt, a + 1, b)
        drivers = sorted(pnl.items(), key=lambda kv: -abs(kv[1]))[:3]
        rows.append(
            {
                "month": days[b].isoformat()[:7],
                "return": _r(equity[b] / equity[a] - 1.0),
                "drivers": [{"symbol": s, "profit": round(v, 2)} for s, v in drivers],
            }
        )
    ordered = sorted(rows, key=lambda r: r["return"] or 0.0)
    return {"best": ordered[::-1][:top], "worst": ordered[:top]}


def risk(
    rebuilt: Mapping[str, Any], classify: Mapping[str, tuple[str, str]], window: int = 252
) -> dict[str, Any] | None:
    """Euler contributions to the final book's volatility, by holding and sector."""
    days, book, equity, prices = (
        rebuilt["days"],
        rebuilt["book"],
        rebuilt["equity"],
        rebuilt["prices"],
    )
    if not book or not book[-1] or equity[-1] <= 0:
        return None
    held = sorted(book[-1])
    weights = np.array([book[-1][s] / equity[-1] for s in held])
    span = days[-window - 1 :] if len(days) > window else days
    series = []
    for s in held:
        p = [_price_at(prices.get(s, {}), d) for d in span]
        if any(v is None or v <= 0 for v in p):
            return None
        series.append([b / a - 1.0 for a, b in pairwise(p)])  # type: ignore[operator]
    cov = (
        np.cov(np.asarray(series)) * 252
        if len(series) > 1
        else np.asarray([[np.var(series[0]) * 252]])
    )
    var_p = float(weights @ cov @ weights)
    if var_p <= 0:
        return None
    sigma = math.sqrt(var_p)
    rc = weights * (cov @ weights) / sigma
    by_sector: dict[str, float] = defaultdict(float)
    for s, c in zip(held, rc, strict=True):
        by_sector[(classify.get(s) or ("Unclassified", ""))[0] or "Unclassified"] += float(c)
    holdings = sorted(
        (
            {"symbol": s, "weight": _r(float(w), 4), "share_of_risk": _r(float(c) / sigma, 4)}
            for s, w, c in zip(held, weights, rc, strict=True)
        ),
        key=lambda r: -(r["share_of_risk"] or 0.0),
    )
    return {
        "as_of": days[-1].isoformat(),
        "volatility_annual": _r(sigma),
        "invested": _r(float(weights.sum()), 4),
        "holdings": holdings[:15],
        "sectors": sorted(
            ({"sector": k, "share_of_risk": _r(v / sigma, 4)} for k, v in by_sector.items()),
            key=lambda r: -(r["share_of_risk"] or 0.0),
        ),
    }


BUCKETS = (
    (0, 5, "up to a week"),
    (6, 20, "1-4 weeks"),
    (21, 60, "1-3 months"),
    (61, 250, "3-12 months"),
    (251, 10**9, "over a year"),
)


def trades(report: Mapping[str, Any], classify: Mapping[str, tuple[str, str]]) -> dict[str, Any]:
    closed = [t for t in report.get("trades") or [] if not t.get("open")]
    if not closed:
        return {"closed": 0}
    by_bucket = []
    for low, high, label in BUCKETS:
        group = [t for t in closed if low <= int(t.get("days_held") or 0) <= high]
        if group:
            nets = [float(t.get("net") or 0.0) for t in group]
            by_bucket.append(
                {
                    "holding": label,
                    "trades": len(group),
                    "net": round(sum(nets), 2),
                    "win_rate": _r(sum(1 for v in nets if v > 0) / len(nets), 3),
                    "average_return": _r(
                        statistics.fmean(float(t.get("return_pct") or 0.0) for t in group), 4
                    ),
                }
            )
    sector_rows: dict[str, list[float]] = defaultdict(list)
    for t in closed:
        sector_rows[
            (classify.get(str(t["symbol"])) or ("Unclassified", ""))[0] or "Unclassified"
        ].append(float(t.get("net") or 0.0))
    nets = sorted((float(t.get("net") or 0.0) for t in closed), reverse=True)
    gross = sum(v for v in nets if v > 0)
    top_n = max(1, len(nets) // 100)
    wins = [v for v in nets if v > 0]
    losses = [v for v in nets if v < 0]
    return {
        "closed": len(closed),
        "best_1pct_trades": top_n,
        "best_1pct_share_of_gross_profit": _r(sum(nets[:top_n]) / gross) if gross else None,
        "payoff_ratio": _r(statistics.fmean(wins) / abs(statistics.fmean(losses)), 3)
        if wins and losses
        else None,
        "by_holding_period": by_bucket,
        "by_sector": sorted(
            (
                {
                    "sector": k,
                    "trades": len(v),
                    "net": round(sum(v), 2),
                    "win_rate": _r(sum(1 for x in v if x > 0) / len(v), 3),
                }
                for k, v in sector_rows.items()
            ),
            key=lambda r: -r["net"],
        ),
    }


def capacity(report: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> dict[str, Any] | None:
    """Each buy against the stock's median daily turnover over the 60 sessions before it."""
    turnover = rebuilt["turnover"]
    days, equity = rebuilt["days"], rebuilt["equity"]
    index = {d: i for i, d in enumerate(days)}
    entries = []
    for o in report.get("orders") or []:
        if not str(o["side"]).lower().endswith("buy"):
            continue
        d = date.fromisoformat(str(o["day"]))
        series = turnover.get(str(o["symbol"]), {})
        recent = sorted(series[k] for k in sorted(series) if k < d)[-60:]
        if not recent or d not in index:
            continue
        median = recent[len(recent) // 2]
        value = float(o["quantity"]) * float(o["price"])
        eq = equity[index[d]]
        if median <= 0 or eq <= 0:
            continue
        entries.append(
            {
                "symbol": str(o["symbol"]),
                "day": d.isoformat(),
                "days_to_trade": value / (PARTICIPATION * median),
                "capital_for_one_day": PARTICIPATION * median / (value / eq),
            }
        )
    if not entries:
        return None
    entries.sort(key=lambda e: e["capital_for_one_day"])
    caps = [e["capital_for_one_day"] for e in entries]
    days_list = sorted(e["days_to_trade"] for e in entries)
    return {
        "entries": len(entries),
        "participation": PARTICIPATION,
        "median_days_to_trade": _r(days_list[len(days_list) // 2], 3),
        "p90_days_to_trade": _r(days_list[int(0.9 * (len(days_list) - 1))], 3),
        "capital_where_90pct_trade_in_a_day": round(caps[int(0.1 * (len(caps) - 1))], 0),
        "capital_where_median_trades_in_a_day": round(caps[len(caps) // 2], 0),
        "tightest": [
            {
                "symbol": e["symbol"],
                "day": e["day"],
                "capital_for_one_day": round(e["capital_for_one_day"], 0),
            }
            for e in entries[:5]
        ],
    }


def exposure(rebuilt: Mapping[str, Any]) -> dict[str, Any]:
    """Invested share, holdings and effective holdings by year; positions held
    after their stock's last price (renamed or delisted while held)."""
    days, book, equity, prices = (
        rebuilt["days"],
        rebuilt["book"],
        rebuilt["equity"],
        rebuilt["prices"],
    )
    per_year: dict[int, list[tuple[float, int, float]]] = defaultdict(list)
    for d, b, e in zip(days, book, equity, strict=False):
        if e <= 0:
            continue
        weights = [v / e for v in b.values()]
        concentration = sum(w * w for w in weights)
        per_year[d.year].append(
            (sum(weights), len(weights), 1 / concentration if concentration else 0.0)
        )
    last_price_day = {s: max(p) for s, p in prices.items() if p}
    frozen: dict[str, dict[str, Any]] = {}
    for d, b in zip(days, book, strict=False):
        for s, v in b.items():
            stale = last_price_day.get(s)
            if stale is not None and (d - stale).days > 10:
                entry = frozen.setdefault(
                    s,
                    {
                        "symbol": s,
                        "last_price": stale.isoformat(),
                        "held_until": d.isoformat(),
                        "value": v,
                    },
                )
                entry["held_until"] = d.isoformat()
    invested = [x[0] for v in per_year.values() for x in v]
    return {
        "invested_mean": _r(statistics.fmean(invested), 3) if invested else None,
        "invested_max": _r(max(invested), 3) if invested else None,
        "by_year": [
            {
                "year": y,
                "invested": _r(statistics.fmean(x[0] for x in v), 3),
                "holdings": _r(statistics.fmean(x[1] for x in v), 1),
                "effective_holdings": _r(statistics.fmean(x[2] for x in v), 1),
            }
            for y, v in sorted(per_year.items())
        ],
        "frozen": sorted(frozen.values(), key=lambda f: f["last_price"]),
        "note": "Invested above 100% means negative cash. A frozen position is one held after "
        "its stock's last price in the panel (renamed or delisted): the engine can neither "
        "sell nor re-price it, and buys around it (research 115).",
    }


# --- the whole thing ---------------------------------------------------------------

_CACHE: dict[str, dict[str, Any]] = {}


def analyse_detail(report: Mapping[str, Any], *, key: str = "") -> dict[str, Any]:
    """Every detailed view for one report; cached by `key` (the report's file and mtime)."""
    if key and key in _CACHE:
        return _CACHE[key]
    from eulerlab.attribution import _classification, _nifty, _spy

    began = time.monotonic()
    asset_class = str(report.get("asset_class") or "equity")
    supported = asset_class in {"equity", "us"}
    if asset_class == "us":
        try:
            from eulerlab.features import us_panel

            classify = {symbol: (sector, "") for symbol, sector in us_panel.sectors().items()}
        except Exception:
            classify = {}
        try:
            market_levels = _spy()
        except Exception:
            market_levels = {}
        market_label = "SPY (S&P 500 ETF)"
        factor_market_label = "Mkt-RF (Ken French U.S. market factor)"
    else:
        try:
            classify = _classification()
        except Exception:
            classify = {}
        try:
            market_levels = _nifty() if asset_class == "equity" else {}
        except Exception:
            market_levels = {}
        market_label = "NIFTYBEES"
        factor_market_label = market_label
    rows = _panel_rows(asset_class) if supported else []
    rebuilt = rebuild(report, rows)
    trusted = rebuilt["max_gap"] is not None and rebuilt["max_gap"] <= REBUILD_TOLERANCE
    base = monthly_base("equity") if asset_class == "equity" else None
    house: dict[str, dict[str, float]] = {}
    risk_free_by_month: dict[str, float] | None = None
    factor_source = None
    if asset_class == "us":
        from eulerlab.factor_sources import us_fama_french_monthly

        factor_source = us_fama_french_monthly()
        library_months = (factor_source or {}).get("monthly", {})
        house = {
            month: {
                "market": values["Mkt-RF"],
                "size": values["SMB"],
                "value": values["HML"],
                "profitability": values["RMW"],
                "investment": values["CMA"],
                "momentum": values["Mom"],
            }
            for month, values in library_months.items()
            if all(k in values for k in ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF"))
        }
        risk_free_by_month = {
            month: values["RF"] for month, values in library_months.items() if month in house
        }
    elif asset_class == "equity":
        house = house_factors(base or {})
    if asset_class == "us" and factor_source:
        factor_model = factors(
            rebuilt,
            house,
            market_levels,
            market_label=factor_market_label,
            risk_free=risk_free_by_month,
            model_name="Fama/French 5 factors + momentum",
            source_url=str(factor_source.get("source") or ""),
            factor_description=(
                "Monthly U.S. Mkt-RF, SMB, HML, RMW, CMA and Mom; strategy returns are in excess of RF."
            ),
        )
    elif asset_class == "equity":
        factor_model = factors(rebuilt, house, market_levels, market_label=factor_market_label)
    else:
        factor_model = None
    factor_note = None
    if not supported:
        factor_note = "Detailed equity factor attribution is available for NSE and U.S. equity reports. This report's asset class has no matching factor panel yet."
    elif asset_class == "us" and not factor_source:
        factor_note = (
            "The official U.S. Fama/French factor files could not be loaded and no local copy is available. "
            "The S&P 500 comparison still uses SPY; retry when the public factor source is reachable."
        )
    elif factor_model is None:
        if asset_class == "us":
            ends = _month_ends(rebuilt["days"])
            report_months = {rebuilt["days"][b].isoformat()[:7] for _, b in pairwise(ends)}
            available = len(report_months & house.keys() & (risk_free_by_month or {}).keys())
            required = len(house[next(iter(house))]) + 12 if house else 18
            factor_note = (
                f"The official factor library is available through {(factor_source or {}).get('latest_month')}, "
                f"but this report has {available} matched monthly observations; this six-factor regression "
                f"needs at least {required}."
            )
        else:
            factor_note = (
                f"The model needs at least 16 matched monthly returns after its 12-month factor lookback. "
                f"The {factor_market_label} factor panel currently provides {len(house)} candidate months. "
                "The factor card will appear when the panel has enough history."
            )
    elif asset_class == "us":
        factor_note = (
            f"Official U.S. Fama/French 5 + momentum returns through {(factor_source or {}).get('latest_month')}; "
            "the model includes the published risk-free rate. Mkt-RF is a broad U.S. market factor, while "
            "the separate benchmark comparison uses SPY. Factor returns are gross of costs; the strategy "
            "return includes its run costs. This report has a relatively short sample for six factors, "
            "so exposure estimates can be unstable."
        )
    else:
        factor_note = (
            "These monthly custom long-short spreads are built from the point-in-time NSE panel. Size uses turnover "
            "as a market-cap proxy; the factors are not Fama-French or vendor factor returns. Spreads are "
            "gross of costs while the strategy return includes its run costs. Value and profitability are omitted "
            "until point-in-time book-to-market and accounting data are available."
        )
    brinson_note = None
    if asset_class == "us":
        brinson_note = (
            "U.S. Brinson sector attribution is withheld because historical sector weights and constituent "
            "membership are not available point in time. The S&P 500 comparison remains in Performance drivers."
        )
    elif asset_class != "equity":
        brinson_note = (
            "Brinson-Fachler sector attribution is currently available for NSE equity reports only."
        )
    out: dict[str, Any] = {
        "market_label": market_label,
        "rebuild": {
            "max_gap": _r(rebuilt["max_gap"], 4),
            "trusted": trusted,
            "note": "Daily holdings rebuilt from the fills and today's adjusted closes; the "
            "holdings-based views need the rebuilt equity within 2% of the stored curve.",
        },
        "factors": factor_model,
        "factor_note": factor_note,
        "brinson_note": brinson_note,
        "rolling": rolling(rebuilt, market_levels) if supported else [],
        "trades": trades(report, classify),
        "brinson": None,
        "risk": None,
        "drawdowns": [],
        "months": {"best": [], "worst": []},
        "capacity": capacity(report, rebuilt),
        "exposure": exposure(rebuilt) if trusted else None,
    }
    if trusted and asset_class == "equity":
        out["brinson"] = brinson(rebuilt, benchmark_by_month(base or {}, classify), classify)
    if trusted and asset_class in {"equity", "us"}:
        out["risk"] = risk(rebuilt, classify)
        out["drawdowns"] = drawdowns(rebuilt)
        out["months"] = months(rebuilt)
    if asset_class == "us" and out["capacity"]:
        out["capacity"]["note"] = (
            "U.S. panel volume is from the IEX feed rather than consolidated exchange volume, "
            "so these capacity estimates are a rough lower-bound proxy."
        )
    out["seconds"] = round(time.monotonic() - began, 1)
    if key:
        _CACHE[key] = out
    return out
