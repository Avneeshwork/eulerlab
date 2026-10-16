"""One payload for the Risk screens, built from `book.py`'s arithmetic (ADR-071)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from eulerlab.risk import book as rb
from eulerlab.risk.watch import WatchLevels

OVERLAP = 0.8
"""Two deployments whose daily results correlate above this are close to one bet."""


def _pct(value: float, base: float) -> float:
    return round(value / base, 6) if base > 0 else 0.0


def _short_rupees(value: float) -> str:
    """₹1 L, ₹2.5 L, ₹10,000: enough to tell two deployments apart."""
    if value >= 100_000:
        return f"₹{value / 100_000:g} L"
    return f"₹{value:,.0f}"


def measure(
    books: Sequence[rb.Book], prices: Mapping[str, Mapping[date, float]], days: Sequence[date]
) -> tuple[dict[str, list[float]], dict[str, float]]:
    """Each deployment's rupees a day over the window, and how much of it has prices.

    Holdings are run through past returns; a gap rule adds what it made or
    lost on the nights it was in position.
    """
    parts: dict[str, list[float]] = {}
    coverage: dict[str, float] = {}
    for b in books:
        parts[b.id], coverage[b.id] = rb.scenario_pnl(b, prices, days)
        if b.rule is not None:
            extra = rb.rule_pnl(b.rule, days)
            parts[b.id] = [own + gap for own, gap in zip(parts[b.id], extra, strict=True)]
    return parts, coverage


def _sum(parts: Mapping[str, Sequence[float]], length: int) -> list[float]:
    return [sum(series[i] for series in parts.values()) for i in range(length)]


def what_if(
    books: Sequence[rb.Book],
    candidate: rb.Book,
    prices: Mapping[str, Mapping[date, float]],
) -> dict[str, Any]:
    """The book's risk before and after adding one more deployment.

    The candidate is whatever the strategy would hold today with this much
    money. Nothing is deployed and nothing is stored.
    """
    days = rb.window_days(prices)
    history = max(len(days) - 1, 0)
    if history < rb.MIN_DAYS:
        return {"enough_history": False, "history_days": history}
    parts, _ = measure(books, prices, days)
    added, coverage = measure([candidate], prices, days)
    new = added[candidate.id]
    before = _sum(parts, history)
    after = [a + b for a, b in zip(before, new, strict=True)]
    var_before = rb.quantile_loss(before, 0.95)[0]
    var_after = rb.quantile_loss(after, 0.95)[0]
    own = rb.quantile_loss(new, 0.95)[0]
    equity_before = sum(b.equity for b in books)
    equity_after = equity_before + candidate.equity
    alike: list[tuple[float, str]] = sorted(
        (round(c, 3), b.title) for b in books if (c := rb.correlation(parts[b.id], new)) is not None
    )
    return {
        "enough_history": True,
        "history_days": history,
        "var_before": round(var_before, 2),
        "var_after": round(var_after, 2),
        "var_added": round(var_after - var_before, 2),
        "var_own": round(own, 2),
        "var_before_pct": _pct(var_before, equity_before),
        "var_after_pct": _pct(var_after, equity_after),
        "correlation_with_book": _round(rb.correlation(before, new), 3) if books else None,
        "most_alike": ({"title": alike[-1][1], "correlation": alike[-1][0]} if alike else None),
        "coverage": round(coverage[candidate.id], 4),
        "names": len(candidate.holdings),
        "gap": rb.gap_summary(candidate.rule, days) if candidate.rule else None,
    }


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def build(
    books: Sequence[rb.Book],
    prices: Mapping[str, Mapping[date, float]],
    sectors: Mapping[str, str],
    *,
    enforced: Mapping[str, float],
    watch: WatchLevels,
    backtests: Mapping[str, Mapping[str, Any]],
    slots: Mapping[str, int] | None = None,
    stopped: Sequence[rb.Book] = (),
) -> dict[str, Any]:
    """Everything the three screens show.

    `enforced` is the kill switch's own limits by name. `backtests` maps a
    strategy id to `{"equity": [...], "worst_drawdown": float}` from its
    stored report, where one exists. `slots` gives each deployment a colour
    that it keeps when another is added or stopped. `stopped` are deployments
    no longer trading: listed with what they made, and in no risk figure.
    """
    days = rb.window_days(prices)
    history = max(len(days) - 1, 0)
    enough = history >= rb.MIN_DAYS
    market = rb.returns_of(prices.get(rb.MARKET, {}), days)
    as_of = max((b.curve[-1][0] for b in books if b.curve), default=None)

    equity = sum(b.equity for b in books)
    capital = sum(b.capital for b in books)
    cash = sum(b.cash for b in books)
    invested = sum(h.value for b in books for h in b.holdings)

    parts, coverage = measure(books, prices, days)
    total = _sum(parts, history)

    table = rb.var_table(total) if enough else []
    var95 = table[0]["var95"] if table else 0.0
    pieces = rb.components(parts, var95) if enough else {}
    standalone = {b.id: rb.quantile_loss(parts[b.id], 0.95)[0] if enough else 0.0 for b in books}
    # The book's VaR with each deployment taken out: what stopping it would do.
    without = {
        b.id: rb.quantile_loss(_sum({k: v for k, v in parts.items() if k != b.id}, history), 0.95)[
            0
        ]
        if enough
        else 0.0
        for b in books
    }
    worst = min(range(history), key=lambda i: total[i]) if total else None

    curve = rb.combined_curve(books)
    book_dd = rb.drawdown(curve)
    names = rb.by_name(books)
    grouped = rb.by_sector(names, sectors)
    betas = {
        row["symbol"]: rb.name_beta(rb.returns_of(prices.get(row["symbol"], {}), days), market)
        for row in names
    }

    # Two deployments of one strategy share a title; the capital tells them apart.
    titles = [b.title for b in books]
    # The capital comes first: a long title is cut short on screen, and a
    # suffix would be the part that is lost.
    label = {
        b.id: f"{_short_rupees(b.capital)} · {b.title}" if titles.count(b.title) > 1 else b.title
        for b in books
    }

    rows: list[dict[str, Any]] = []
    for b in books:
        pnl = parts[b.id]
        _, sd = rb._mean_sd([p / b.equity for p in pnl]) if b.equity > 0 and pnl else (0.0, 0.0)
        dd = rb.drawdown(b.curve)
        tested = backtests.get(b.strategy_id) or {}
        rows.append(
            {
                "id": b.id,
                "strategy_id": b.strategy_id,
                "title": label[b.id],
                "status": b.status,
                "slot": (slots or {}).get(b.id, books.index(b)),
                "capital": round(b.capital, 2),
                "equity": round(b.equity, 2),
                "cash": round(b.cash, 2),
                "invested": round(sum(h.value for h in b.holdings), 2),
                "positions": len(b.holdings),
                "since_start": _pct(b.equity - b.capital, b.capital),
                "today": round(rb.today_pnl(b, as_of), 2),
                "volatility": round(sd * rb.TRADING_DAYS**0.5, 6) if enough else None,
                "var95": round(standalone[b.id], 2) if enough else None,
                "var_share": _pct(pieces.get(b.id, 0.0), var95),
                "var_component": pieces.get(b.id, 0.0),
                "var_without": round(without[b.id], 2) if enough else None,
                "capital_share": _pct(b.equity, equity),
                "beta": _round(rb.beta(pnl, b.equity, market) if b.holdings or b.rule else None, 3),
                "drawdown_now": dd["now"],
                "drawdown_deepest": dd["deepest"],
                "backtest_worst_drawdown": tested.get("worst_drawdown"),
                "days_live": len(b.curve),
                "coverage": round(coverage[b.id], 4),
                "flat": not b.holdings and b.rule is None,
                "gap": rb.gap_summary(b.rule, days) if b.rule else None,
                "against_backtest": rb.against_backtest(b, tested.get("equity") or []),
            }
        )

    ids = [b.id for b in books]
    matrix = [
        [_round(rb.correlation(parts[a], parts[b_]), 3) if enough else None for b_ in ids]
        for a in ids
    ]

    today = sum(row["today"] for row in rows)
    largest_name = abs(names[0]["value"]) if names else 0.0
    worst_deployment = min(rows, key=lambda r: r["drawdown_now"], default=None)
    limits = [
        rb.limit_row(
            "Loss today",
            max(0.0, -today),
            enforced["max_daily_loss"],
            "INR",
            "enforced",
            "Kill switch trips",
        ),
        rb.limit_row(
            "Rupees in one name",
            largest_name,
            enforced["max_position_notional"],
            "INR",
            "enforced",
            "Kill switch trips",
        ),
        rb.limit_row(
            "Book VaR, 1 day 95%",
            _pct(var95, equity) * 100,
            watch.book_var_pct,
            "%",
            "watch",
            "Warning only",
        ),
        rb.limit_row(
            "Book drawdown",
            -book_dd["now"] * 100,
            watch.book_drawdown_pct,
            "%",
            "watch",
            "Warning only",
        ),
        rb.limit_row(
            "Largest sector" + (f" ({grouped[0]['sector']})" if grouped else ""),
            (grouped[0]["share"] * 100) if grouped else 0.0,
            watch.sector_pct,
            "%",
            "watch",
            "Warning only",
        ),
    ]
    if worst_deployment is not None:
        limits.append(
            rb.limit_row(
                f"Deepest deployment drawdown ({worst_deployment['title']})",
                -worst_deployment["drawdown_now"] * 100,
                watch.deployment_drawdown_pct,
                "%",
                "watch",
                "Warning only",
            )
        )
    for b in books:
        gap = rb.gap_summary(b.rule, days) if b.rule else None
        if gap and gap["enough"] and gap["notional"] > 0:
            # Not a new limit: the kill switch's own daily loss, set beside what
            # one bad night in the future costs. The switch trips after the loss.
            limits.append(
                rb.limit_row(
                    "A bad night in the future (1 in 20), against the daily loss limit",
                    gap["var95_when_held"],
                    enforced["max_daily_loss"],
                    "INR",
                    "enforced",
                    "Kill switch trips, after the gap",
                )
            )
    limits.sort(key=lambda row: -row["used"])

    pairs = [
        {"a": rows[i]["title"], "b": rows[j]["title"], "correlation": matrix[i][j]}
        for i in range(len(ids))
        for j in range(i + 1, len(ids))
        if (matrix[i][j] or 0.0) >= OVERLAP
    ]
    shared = [row for row in names if len(row["held_by"]) > 1]

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "history_days": history,
        "enough_history": enough,
        "window": [days[0].isoformat(), days[-1].isoformat()] if days else None,
        "book": {
            "deployments": len(books),
            "capital": round(capital, 2),
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "exposure": _pct(invested, equity),
            "today": round(today, 2),
            "today_pct": _pct(today, equity - today),
            "since_start": round(equity - capital, 2),
            "since_start_pct": _pct(equity - capital, capital),
            "var95": var95,
            "var95_pct": _pct(var95, equity),
            "es95": table[0]["es95"] if table else 0.0,
            "var99": table[0]["var99"] if table else 0.0,
            "standalone_sum": round(sum(standalone.values()), 2),
            "diversification": round(sum(standalone.values()) - var95, 2),
            "beta": _round(rb.beta(total, equity, market) if invested else None, 3),
            "volatility": round(
                rb._mean_sd([p / equity for p in total])[1] * rb.TRADING_DAYS**0.5, 6
            )
            if enough and equity > 0
            else None,
            "drawdown": book_dd,
            "curve": [[day.isoformat(), value] for day, value in curve],
            "names": len(names),
            "shared_names": len(shared),
            "coverage": round(
                sum(coverage[b.id] * sum(abs(h.value) for h in b.holdings) for b in books)
                / (sum(abs(h.value) for b in books for h in b.holdings) or 1.0),
                4,
            )
            if invested
            else 1.0,
        },
        "var": {
            "methods": table,
            "histogram": rb.histogram(total, equity) if enough else [],
            "worst_day": (
                {
                    "day": days[worst + 1].isoformat(),
                    "pnl": round(total[worst], 2),
                    "pct": _pct(total[worst], equity),
                }
                if worst is not None
                else None
            ),
        },
        "deployments": rows,
        "names": [
            {
                "symbol": row["symbol"],
                "value": round(row["value"], 2),
                "share": _pct(abs(row["value"]), equity),
                "held_by": len(row["held_by"]),
                "sector": sectors.get(row["symbol"]) or "Unclassified",
            }
            for row in names[:12]
        ],
        "sectors": grouped,
        "correlation": {"ids": ids, "titles": [row["title"] for row in rows], "matrix": matrix},
        "alike": pairs,
        "stress": rb.stress(
            names,
            betas,
            sectors,
            equity,
            (days[worst + 1].isoformat(), total[worst]) if worst is not None and enough else None,
            gap_notional=sum(b.rule.notional for b in books if b.rule),
            worst_gap=next(
                (
                    (b.rule.worst[0].isoformat(), b.rule.worst[1])
                    for b in books
                    if b.rule and b.rule.worst
                ),
                None,
            ),
        ),
        "stopped": [
            {
                "id": b.id,
                "title": b.title,
                "slot": (slots or {}).get(b.id, len(books)),
                "capital": round(b.capital, 2),
                "equity": round(b.equity, 2),
                "made": round(b.equity - b.capital, 2),
                "made_pct": _pct(b.equity - b.capital, b.capital),
                "days_live": len(b.curve),
                "last_day": b.curve[-1][0].isoformat() if b.curve else None,
            }
            for b in stopped
        ],
        "limits": limits,
        "watch_note": (
            "Rows marked 'watch' are warning levels from config/risk_watch.yaml. "
            "They do not stop or reduce anything. The kill switch's own limits do."
        ),
    }
