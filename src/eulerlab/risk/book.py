"""The deployed book as one thing: roll-up, value at risk, stress, exposure (ADR-071).

Operator, 2026-10-14: "a screen which shows risk on current trading
strategies: current VaR, strategy distribution, maximum risk, allocation in
different strategies". Until now each deployment was shown alone and the only
risk figures were the kill switch's counts (research 079).

Everything here is arithmetic on values handed in: the deployments' stored
books, a table of adjusted closes, sectors. Nothing reads a file, places an
order or stops one. `api/risk_routes.py` gathers the inputs.

### How the risk numbers are made

A deployment is days old, so its own returns cannot give a value at risk.
Instead **today's holdings are run through the last `WINDOW` trading days**:
for each past day, what would this exact book have made or lost? That gives a
profit-and-loss history for the book as it stands now, and every figure below
is read from it.

- **VaR** at 95% is the loss that history exceeded on one day in twenty
  (`quantile_loss`, nearest rank). **Expected shortfall** is the average loss
  on those days.
- **Three methods**, shown side by side: that history as it is; a normal
  curve with the history's mean and spread; and a normal curve whose spread
  weights recent days more (`LAMBDA`, the RiskMetrics convention).
- **Component VaR** splits the book's VaR between deployments in proportion
  to each one's covariance with the book. The parts sum to the whole.
- **Stress** moves each holding by a stated shock, through its beta to the
  Nifty where the shock is a market move.

What this cannot see: a holding with no price on a past day counts as flat
that day (`coverage` says how much of the book that is); a deployment that
holds nothing at the close has no risk here even if it trades overnight;
nothing is assumed about liquidity, so a loss is what the closes say.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any

WINDOW = 250
"""Trading days of history the book is run through: about a year."""

# ASSUMPTION: A-059 — the weight on yesterday in the recent-weighted spread.
LAMBDA = 0.94
"""RiskMetrics' daily decay. Not fitted to anything here."""

Z = {0.95: 1.6448536269514722, 0.99: 2.3263478740408408}
TRADING_DAYS = 252
MIN_DAYS = 60
"""Fewer past days than this and no risk figure is given: a VaR from a few
weeks is a guess with a rupee sign."""
MIN_GAP_NIGHTS = 30
"""Signal nights in the window before a "when it holds" VaR is given."""
MIN_BAND_DAYS = 20
"""Days live before a deployment is judged against its backtest."""
MARKET = "NIFTYBEES"
"""The Nifty 50 ETF, which is in the price panel. Betas are measured to it."""


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: float
    price: float
    value: float


@dataclass(frozen=True)
class GapRule:
    """A position held only from one close to the next open (ADR-072).

    The overnight futures deployment buys at the close on a signal day and
    sells at the next open. At every close its book is empty, so holdings say
    it has no risk, while on a night it trades it carries the whole gap on a
    lot worth more than most of the other deployments together.

    `gaps` and `held` are keyed by the **morning** the position is closed, so
    a gap sits on the same day as the close-to-close return it is part of.
    """

    contract: str
    lots: int
    lot_size: int
    notional: float
    """Rupees it would buy on a signal night, at today's equity and price."""
    gaps: Mapping[date, float]
    """Open over the previous close, less one, for the near contract."""
    held: frozenset[date]
    """Mornings on which the rule had been in position overnight."""
    held_now: float = 0.0
    """Rupees it holds tonight, from its own book. Zero on most nights."""
    worst: tuple[date, float] | None = None
    """The worst gap in the whole futures history, held or not: (morning, return)."""


@dataclass(frozen=True)
class Book:
    """One deployment as it stands: what it holds and where its equity has been."""

    id: str
    strategy_id: str
    title: str
    capital: float
    equity: float
    cash: float
    holdings: tuple[Holding, ...]
    curve: tuple[tuple[date, float], ...]
    status: str = "active"
    note: str = ""
    rule: GapRule | None = None
    """Set for a deployment whose risk is a gap, not a holding at the close."""


def book_from_state(
    deployment_id: str,
    strategy_id: str,
    title: str,
    capital: float,
    status: str,
    state: Mapping[str, Any] | None,
) -> Book:
    """A `Book` from a deployment's stored state. No state yet means all cash."""
    state = state or {}
    holdings = tuple(
        Holding(
            symbol=str(row["symbol"]),
            quantity=float(row.get("quantity") or 0),
            price=float(row.get("last_price") or 0),
            value=float(row.get("value") or 0),
        )
        for row in state.get("book") or []
        if row.get("symbol") and float(row.get("value") or 0) != 0
    )
    curve = tuple(
        (date.fromisoformat(str(day)), float(value)) for day, value in state.get("curve") or []
    )
    equity = float(state.get("equity") or capital)
    return Book(
        id=deployment_id,
        strategy_id=strategy_id,
        title=title,
        capital=float(capital),
        equity=equity,
        cash=float(capital if state.get("cash") is None else state["cash"]),
        holdings=holdings,
        curve=curve,
        status=status,
    )


# --- the book run through history ---------------------------------------------------


def window_days(prices: Mapping[str, Mapping[date, float]], window: int = WINDOW) -> list[date]:
    """The last `window + 1` days on which the market traded, oldest first."""
    days = sorted({day for series in prices.values() for day in series})
    return days[-(window + 1) :]


def returns_of(series: Mapping[date, float], days: Sequence[date]) -> list[float | None]:
    """Day-on-day returns over `days`; None where either close is missing."""
    out: list[float | None] = []
    for before, after in pairwise(days):
        a, b = series.get(before), series.get(after)
        out.append(b / a - 1 if a and b and a > 0 else None)
    return out


def scenario_pnl(
    book: Book, prices: Mapping[str, Mapping[date, float]], days: Sequence[date]
) -> tuple[list[float], float]:
    """(rupees a day, share of the holdings' value that has a full history).

    Each past day's return is applied to today's rupee value in each name. A
    name with no price on a day is flat that day.
    """
    pnl = [0.0] * max(len(days) - 1, 0)
    invested = sum(abs(h.value) for h in book.holdings)
    covered = 0.0
    for holding in book.holdings:
        moves = returns_of(prices.get(holding.symbol, {}), days)
        known = sum(1 for move in moves if move is not None)
        if moves and known == len(moves):
            covered += abs(holding.value)
        for index, move in enumerate(moves):
            if move is not None:
                pnl[index] += holding.value * move
    return pnl, (covered / invested if invested else 1.0)


def rule_pnl(rule: GapRule, days: Sequence[date]) -> list[float]:
    """Rupees a day from the rule as it was run: the gap on nights it held, else nothing."""
    return [
        rule.notional * rule.gaps[day] if day in rule.held and day in rule.gaps else 0.0
        for day in days[1:]
    ]


def gap_summary(rule: GapRule, days: Sequence[date]) -> dict[str, Any]:
    """What a night in position can cost, read from the nights it was held.

    `when_held` uses only signal nights in the window: the position is never
    open on any other night, so those are the gaps it can actually meet.
    """
    window = [day for day in days[1:] if day in rule.gaps]
    nights = [rule.notional * rule.gaps[day] for day in window if day in rule.held]
    var95, es95 = quantile_loss(nights, 0.95) if len(nights) >= MIN_GAP_NIGHTS else (0.0, 0.0)
    worst_held = min(
        ((day, rule.notional * rule.gaps[day]) for day in window if day in rule.held),
        key=lambda item: item[1],
        default=None,
    )
    return {
        "contract": rule.contract,
        "lots": rule.lots,
        "lot_size": rule.lot_size,
        "notional": round(rule.notional, 2),
        "nights": len(window),
        "nights_held": len(nights),
        "held_share": round(len(nights) / len(window), 4) if window else 0.0,
        "enough": len(nights) >= MIN_GAP_NIGHTS,
        "var95_when_held": round(var95, 2),
        "es95_when_held": round(es95, 2),
        "worst_night": (
            {"day": worst_held[0].isoformat(), "pnl": round(worst_held[1], 2)}
            if worst_held and worst_held[1] < 0
            else None
        ),
        "holds_tonight": rule.held_now > 0,
        "held_now": round(rule.held_now, 2),
        "worst_ever": (
            {
                "day": rule.worst[0].isoformat(),
                "gap": round(rule.worst[1], 6),
                "pnl": round(rule.notional * rule.worst[1], 2),
            }
            if rule.worst
            else None
        ),
    }


def quantile_loss(pnl: Sequence[float], confidence: float) -> tuple[float, float]:
    """(VaR, expected shortfall) as positive rupees, by nearest rank.

    VaR is the k-th worst day, k = the days outside the confidence level,
    rounded up and at least one. A book that never lost has a VaR of zero.
    """
    if not pnl:
        return 0.0, 0.0
    ordered = sorted(pnl)
    # Rounded first: (1 - 0.95) * 100 is 5.000000000000004 in floating point,
    # and its ceiling would take a sixth day into a five-day tail.
    k = max(1, math.ceil(round((1 - confidence) * len(ordered), 9)))
    tail = ordered[:k]
    return max(0.0, -tail[-1]), max(0.0, -sum(tail) / len(tail))


def _mean_sd(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else 0.0), 0.0
    mean = sum(values) / len(values)
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _normal_tail(mean: float, sd: float, confidence: float) -> tuple[float, float]:
    """VaR and expected shortfall of a normal curve, as positive rupees."""
    z = Z[confidence]
    density = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    return max(0.0, z * sd - mean), max(0.0, sd * density / (1 - confidence) - mean)


def recent_sd(pnl: Sequence[float], decay: float = LAMBDA) -> float:
    """Spread with yesterday weighted most: weights fall by `decay` a day back."""
    if not pnl:
        return 0.0
    weight, total, norm = 1.0, 0.0, 0.0
    for value in reversed(pnl):
        total += weight * value * value
        norm += weight
        weight *= decay
    return math.sqrt(total / norm) if norm else 0.0


def var_table(pnl: Sequence[float]) -> list[dict[str, Any]]:
    """The three methods, each at 95% and 99%."""
    mean, sd = _mean_sd(pnl)
    recent = recent_sd(pnl)
    methods: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = [
        (
            "historical",
            f"History, {len(pnl)} days",
            quantile_loss(pnl, 0.95),
            quantile_loss(pnl, 0.99),
        ),
        ("normal", "Normal curve", _normal_tail(mean, sd, 0.95), _normal_tail(mean, sd, 0.99)),
        (
            "recent",
            "Normal curve, recent days weighted",
            _normal_tail(0.0, recent, 0.95),
            _normal_tail(0.0, recent, 0.99),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for key, label, (var95, es95), (var99, es99) in methods:
        rows.append(
            {
                "method": key,
                "label": label,
                "var95": round(var95, 2),
                "var99": round(var99, 2),
                "es95": round(es95, 2),
                "es99": round(es99, 2),
            }
        )
    return rows


def covariance(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 2 or len(a) != len(b):
        return 0.0
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    return sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / (len(a) - 1)


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """None when either series does not move: a flat book correlates with nothing."""
    var_a, var_b = covariance(a, a), covariance(b, b)
    if var_a <= 0 or var_b <= 0:
        return None
    return covariance(a, b) / math.sqrt(var_a * var_b)


def components(parts: Mapping[str, Sequence[float]], total_var: float) -> dict[str, float]:
    """Each part's rupees of the book's VaR. They sum to `total_var`.

    A part's share is its covariance with the book over the book's variance:
    the Euler split, which is exact for a normal book and the usual
    approximation otherwise. A part that moves against the book has a
    negative share: it is reducing the risk.
    """
    if not parts:
        return {}
    length = len(next(iter(parts.values())))
    book = [sum(series[i] for series in parts.values()) for i in range(length)]
    variance = covariance(book, book)
    if variance <= 0:
        return dict.fromkeys(parts, 0.0)
    return {
        name: round(total_var * covariance(series, book) / variance, 2)
        for name, series in parts.items()
    }


def beta(pnl: Sequence[float], equity: float, market: Sequence[float | None]) -> float | None:
    """The book's return per unit of the market's, over days the market traded."""
    pairs = [
        (p / equity, m) for p, m in zip(pnl, market, strict=False) if m is not None and equity > 0
    ]
    if len(pairs) < MIN_DAYS:
        return None
    own, mkt = [p for p, _ in pairs], [m for _, m in pairs]
    variance = covariance(mkt, mkt)
    return covariance(own, mkt) / variance if variance > 0 else None


def name_beta(own: Sequence[float | None], market: Sequence[float | None]) -> float | None:
    """One name's beta to the market, over the days both have a return."""
    pairs = [(o, m) for o, m in zip(own, market, strict=False) if o is not None and m is not None]
    if len(pairs) < MIN_DAYS:
        return None
    mine, mkt = [o for o, _ in pairs], [m for _, m in pairs]
    variance = covariance(mkt, mkt)
    return covariance(mine, mkt) / variance if variance > 0 else None


def histogram(pnl: Sequence[float], equity: float, bins: int = 12) -> list[dict[str, float]]:
    """Daily results as % of equity, counted into equal bins centred on zero."""
    if not pnl or equity <= 0:
        return []
    moves = [p / equity * 100 for p in pnl]
    # The range covers the 1st to 99th percentile; the few days beyond are
    # counted into the end bins. One freak day would otherwise set the scale
    # and leave every ordinary day in two bars.
    ordered = sorted(moves)
    edge = max(0, round(0.01 * len(ordered)) - 1) if len(ordered) >= 100 else 0
    reach = max(abs(ordered[edge]), abs(ordered[-1 - edge]), 1e-9)
    # A round edge, so the axis reads 2.5% rather than 2.3718%.
    step = next(
        s for s in (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 100.0) if s * bins / 2 >= reach
    )
    low = -step * bins / 2
    counts = [0] * bins
    for move in moves:
        counts[min(bins - 1, max(0, int((move - low) / step)))] += 1
    return [
        {"from": round(low + i * step, 4), "to": round(low + (i + 1) * step, 4), "days": count}
        for i, count in enumerate(counts)
    ]


# --- equity paths -------------------------------------------------------------------


def drawdown(curve: Sequence[tuple[date, float]]) -> dict[str, Any]:
    """Where equity sits below its highest point so far, and the deepest it has been."""
    peak = 0.0
    peak_day: date | None = None
    deepest, deepest_day = 0.0, None
    path: list[tuple[str, float]] = []
    now = 0.0
    for day, value in curve:
        if value > peak:
            peak, peak_day = value, day
        now = value / peak - 1 if peak > 0 else 0.0
        if now < deepest:
            deepest, deepest_day = now, day
        path.append((day.isoformat(), round(now, 6)))
    return {
        "now": round(now, 6),
        "deepest": round(deepest, 6),
        "deepest_day": deepest_day.isoformat() if deepest_day else None,
        "peak_day": peak_day.isoformat() if peak_day else None,
        "path": path,
    }


def combined_curve(books: Sequence[Book]) -> list[tuple[date, float]]:
    """The whole book's equity by day.

    A deployment counts at its capital before its first day and at its last
    known equity after its latest, so the sum is always all the money.
    """
    days = sorted({day for book in books for day, _ in book.curve})
    out: list[tuple[date, float]] = []
    last = {book.id: book.capital for book in books}
    by_day = [dict(book.curve) for book in books]
    for day in days:
        for book, curve in zip(books, by_day, strict=True):
            if day in curve:
                last[book.id] = curve[day]
        out.append((day, round(sum(last.values()), 2)))
    return out


def today_pnl(book: Book, as_of: date | None) -> float:
    """The last day's change in equity, if the curve reaches `as_of`."""
    if len(book.curve) < 2 or (as_of is not None and book.curve[-1][0] != as_of):
        return 0.0
    return book.curve[-1][1] - book.curve[-2][1]


def backtest_band(
    backtest: Sequence[float],
    days_live: int,
    quantiles: tuple[float, float, float] = (0.05, 0.5, 0.95),
) -> list[dict[str, float]]:
    """Where the backtest says equity should be after 1..`days_live` days.

    For each horizon, every stretch of that many days in the backtest gives
    one return; the band is the 5th, 50th and 95th percentile of them, with
    the start at 100. Overlapping stretches, so the percentiles are smoother
    than the number of independent periods deserves.
    """
    out: list[dict[str, float]] = [{"day": 0, "low": 100.0, "mid": 100.0, "high": 100.0}]
    for horizon in range(1, days_live + 1):
        moves = sorted(
            backtest[i + horizon] / backtest[i]
            for i in range(len(backtest) - horizon)
            if backtest[i] > 0
        )
        if len(moves) < 20:
            break
        low, mid, high = (moves[min(len(moves) - 1, int(q * len(moves)))] for q in quantiles)
        out.append(
            {
                "day": horizon,
                "low": round(low * 100, 3),
                "mid": round(mid * 100, 3),
                "high": round(high * 100, 3),
            }
        )
    return out


def against_backtest(book: Book, backtest: Sequence[float]) -> dict[str, Any]:
    """The live path beside its backtest band, and a one-word verdict."""
    live = [{"day": 0, "value": 100.0}] + [
        {"day": i, "value": round(value / book.capital * 100, 3)}
        for i, (_, value) in enumerate(book.curve, start=1)
    ]
    days_live = len(book.curve)
    band = backtest_band(backtest, days_live) if backtest else []
    verdict, expected = "no_backtest", None
    if band and len(band) > days_live and days_live:
        end, got = band[days_live], live[-1]["value"]
        expected = round(end["mid"] / 100 - 1, 6)
        if days_live < MIN_BAND_DAYS:
            verdict = "too_early"
        else:
            verdict = "below" if got < end["low"] else "above" if got > end["high"] else "inside"
    elif not days_live:
        verdict = "not_started"
    return {"live": live, "band": band, "verdict": verdict, "expected": expected}


# --- exposure -----------------------------------------------------------------------


def by_name(books: Sequence[Book]) -> list[dict[str, Any]]:
    """Every name held, added up across deployments, largest first."""
    totals: dict[str, dict[str, Any]] = {}
    for book in books:
        for holding in book.holdings:
            row = totals.setdefault(
                holding.symbol, {"symbol": holding.symbol, "value": 0.0, "held_by": []}
            )
            row["value"] += holding.value
            row["held_by"].append(book.id)
    return sorted(totals.values(), key=lambda r: (-abs(r["value"]), r["symbol"]))


def by_sector(
    names: Sequence[Mapping[str, Any]], sectors: Mapping[str, str]
) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for row in names:
        sector = sectors.get(row["symbol"]) or "Unclassified"
        totals[sector] = totals.get(sector, 0.0) + abs(row["value"])
    invested = sum(totals.values())
    return [
        {
            "sector": sector,
            "value": round(value, 2),
            "share": round(value / invested, 6) if invested else 0.0,
        }
        for sector, value in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]


# --- stress -------------------------------------------------------------------------


def stress(
    names: Sequence[Mapping[str, Any]],
    betas: Mapping[str, float | None],
    sectors: Mapping[str, str],
    equity: float,
    worst_day: tuple[str, float] | None,
    gap_notional: float = 0.0,
    worst_gap: tuple[str, float] | None = None,
) -> list[dict[str, Any]]:
    """What today's holdings lose in each named bad day, as negative rupees.

    A market fall reaches each name through its own beta to the Nifty; a name
    with no measured beta is taken to move with the market (beta 1).
    """

    def market(shock: float) -> float:
        return float(sum(row["value"] * (betas.get(row["symbol"]) or 1.0) * shock for row in names))

    out: list[dict[str, Any]] = [
        {
            "key": "nifty_13",
            "label": "Nifty falls 13% in a day",
            "note": "as on 23 March 2020, by each holding's beta",
            "loss": market(-0.13),
        },
        {
            "key": "nifty_10",
            "label": "Nifty falls 10% in a day",
            "note": "by each holding's beta",
            "loss": market(-0.10),
        },
        {
            "key": "nifty_5",
            "label": "Nifty falls 5% in a day",
            "note": "by each holding's beta",
            "loss": market(-0.05),
        },
    ]
    if worst_day is not None:
        out.append(
            {
                "key": "worst_day",
                "label": "The worst day of the last year, again",
                "note": worst_day[0],
                "loss": worst_day[1],
            }
        )
    grouped = by_sector(names, sectors)
    if grouped:
        top = grouped[0]
        out.append(
            {
                "key": "sector",
                "label": f"{top['sector']} falls 8%, the rest flat",
                "note": "the largest sector",
                "loss": -0.08 * top["value"],
            }
        )
    if names:
        out.append(
            {
                "key": "name",
                "label": "The largest name falls 20%",
                "note": names[0]["symbol"],
                "loss": -0.20 * abs(names[0]["value"]),
            }
        )
    if gap_notional > 0:
        # A fall in the market overnight reaches the future one for one, on
        # top of what it does to the shares. Shown apart, because it applies
        # only on a night the future is held.
        out.append(
            {
                "key": "gap_3",
                "label": "The future is held and opens 3% lower",
                "note": "the futures position alone",
                "loss": -0.03 * gap_notional,
            }
        )
        if worst_gap is not None:
            out.append(
                {
                    "key": "gap_worst",
                    "label": "The future is held through its worst gap on record",
                    "note": f"{worst_gap[0]}, {worst_gap[1] * 100:.1f}%; the futures position alone",
                    "loss": worst_gap[1] * gap_notional,
                }
            )
    for row in out:
        row["loss"] = round(min(0.0, row["loss"]), 2)
        row["share"] = round(row["loss"] / equity, 6) if equity > 0 else 0.0
    return out


# --- limits -------------------------------------------------------------------------


def limit_row(
    name: str, now: float, limit: float, unit: str, kind: str, when: str, *, near: float = 0.75
) -> dict[str, Any]:
    """One limit with how much of it is used. `kind` is `enforced` or `watch`."""
    used = max(0.0, now / limit) if limit > 0 else 0.0
    state = "over" if used >= 1 else "near" if used >= near else "ok"
    return {
        "name": name,
        "now": round(now, 4),
        "limit": limit,
        "unit": unit,
        "used": round(used, 4),
        "state": state,
        "kind": kind,
        "when": when,
    }
