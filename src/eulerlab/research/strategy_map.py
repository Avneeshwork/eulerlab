"""The strategy map: how many different daily strategies do we really hold?

Phase 1 of the multi-strategy research plan (ADR-101). It reads the daily
equity curve of every stored equity backtest report, and answers three
questions without running anything new:

1. **How alike are they?** Pairwise correlation of daily returns, raw and
   after taking out Nifty (NIFTYBEES), over the days both strategies traded.
2. **How many families?** Average-linkage clustering: two groups join while
   the average correlation between their members is at least `join_at`
   (0.7, the plan's proposed line between a new idea and a variant).
3. **How many independent bets?** The participation ratio of the correlation
   matrix's eigenvalues, `(sum λ)² / sum λ²`: N for N uncorrelated strategies,
   1 for N copies of one.

It also reports one fixed book, decided before any number was seen: equal
weight across families, equal weight within a family. There is no search over
books, so no configuration is chosen by looking at results.

### Why this spends no trial

Every report it reads was already run; nothing is re-run, tuned or selected.
The one book is descriptive: its members were run on 2016 to 2026, so it has
already seen any confirmation window and cannot be a gate candidate. It is
printed as a measure of diversification, not as a result.

### What it cannot see

- One report per strategy: the configuration with the longest equity curve
  (ties: the most recent). Other configurations of the same strategy are
  ignored, so a family's spread of settings is not measured here.
- The Nifty hedge uses each strategy's full-sample beta and pays nothing for
  the futures, so hedged figures are an upper bound (S-056).
- A pairwise matrix over unequal windows need not be positive semi-definite;
  negative eigenvalues are clipped to zero before the participation ratio.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from eulerlab.paths import data_path

WORKSPACES = data_path("workspaces")
OUTPUT = data_path("derived/strategy_map.json")
TRADING_DAYS = 252.0

MIN_DAYS = 500
"""A strategy with fewer daily returns than this is left out: two years is the
least that says anything about a daily strategy's correlation."""

MIN_OVERLAP = 250
"""Two strategies must share this many trading days for a correlation to be
reported. Fewer, and the pair is unknown rather than guessed."""

EXCLUDED = frozenset({"buy_and_hold"})
"""Benchmarks, not strategies: holding the market is what the hedge takes out."""

JOIN_AT = 0.7
"""Average correlation at which two groups count as one family (ADR-101)."""

FLAT = 1e-12


@dataclass(frozen=True)
class Series:
    """One strategy's daily simple returns, keyed by the day they were earned."""

    strategy_id: str
    configuration: str
    returns: dict[date, float]


def _returns(days: Sequence[str], values: Sequence[float]) -> dict[date, float]:
    out: dict[date, float] = {}
    for (_, before), (day, after) in pairwise(zip(days, values, strict=True)):
        if before > 0:
            out[date.fromisoformat(day)] = float(after) / float(before) - 1.0
    return out


def _is_flat(returns: Iterable[float]) -> bool:
    return all(abs(r) < FLAT for r in returns)


def collect(root: Path = WORKSPACES, *, min_days: int = MIN_DAYS) -> list[Series]:
    """The longest stored equity report of each equity strategy, as daily returns.

    Only `reports/<strategy>/<configuration>.json` is read (the latest run of a
    configuration); the permanent per-run copies under `runs/` are the same
    numbers and would count a strategy twice.
    """
    chosen: dict[str, tuple[int, str, Series]] = {}
    for path in sorted(root.glob("*/reports/*/*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict) or report.get("asset_class", "equity") != "equity":
            continue
        equity = report.get("equity") or {}
        days, values = equity.get("days") or [], equity.get("values") or []
        if len(days) != len(values) or len(days) <= min_days:
            continue
        returns = _returns(days, values)
        if len(returns) < min_days or _is_flat(returns.values()):
            continue
        strategy_id = str(report.get("strategy_id") or path.parent.name)
        if strategy_id in EXCLUDED:
            continue
        recorded = str((report.get("provenance") or {}).get("recorded_at") or "")
        key = (len(returns), recorded)
        held = chosen.get(strategy_id)
        if held is None or key > (held[0], held[1]):
            series = Series(strategy_id, str(report.get("configuration") or path.stem), returns)
            chosen[strategy_id] = (len(returns), recorded, series)
    return [chosen[k][2] for k in sorted(chosen)]


def _pair(a: dict[date, float], b: dict[date, float]) -> tuple[np.ndarray, np.ndarray]:
    common = sorted(a.keys() & b.keys())
    return (
        np.array([a[d] for d in common], dtype=float),
        np.array([b[d] for d in common], dtype=float),
    )


def correlation(
    a: dict[date, float], b: dict[date, float], *, min_overlap: int = MIN_OVERLAP
) -> float | None:
    """Pearson correlation over the days both series have; None if too few or flat."""
    x, y = _pair(a, b)
    if len(x) < min_overlap or x.std() < FLAT or y.std() < FLAT:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def beta(strategy: dict[date, float], market: dict[date, float]) -> float | None:
    x, m = _pair(strategy, market)
    if len(x) < MIN_OVERLAP or m.var() < FLAT:
        return None
    return float(np.cov(x, m, ddof=0)[0, 1] / m.var())


def hedged(strategy: dict[date, float], market: dict[date, float]) -> dict[date, float] | None:
    """Returns less full-sample beta times the market's, on days both exist."""
    b = beta(strategy, market)
    if b is None:
        return None
    return {d: r - b * market[d] for d, r in strategy.items() if d in market}


def matrix(
    series: Sequence[dict[date, float]], *, min_overlap: int = MIN_OVERLAP
) -> list[list[float | None]]:
    n = len(series)
    out: list[list[float | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        out[i][i] = 1.0
        for j in range(i + 1, n):
            out[i][j] = out[j][i] = correlation(series[i], series[j], min_overlap=min_overlap)
    return out


def families(
    corr: Sequence[Sequence[float | None]], *, join_at: float = JOIN_AT
) -> list[list[int]]:
    """Average-linkage clusters. An unknown pair counts as uncorrelated (0).

    Deterministic: the closest pair of groups joins first, ties broken by the
    lowest member index, and each family is listed in index order.
    """
    groups: list[list[int]] = [[i] for i in range(len(corr))]

    def link(a: list[int], b: list[int]) -> float:
        values = [corr[i][j] for i in a for j in b]
        return sum(v if v is not None else 0.0 for v in values) / len(values)

    while len(groups) > 1:
        best: tuple[float, int, int] | None = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                score = link(groups[i], groups[j])
                if best is None or score > best[0]:
                    best = (score, i, j)
        if best is None or best[0] < join_at:
            break
        _, i, j = best
        groups[i] = sorted(groups[i] + groups[j])
        del groups[j]
    return sorted(groups, key=lambda g: g[0])


def effective_count(corr: Sequence[Sequence[float | None]]) -> float:
    """Participation ratio of the eigenvalues; unknown pairs as 0, negatives clipped."""
    n = len(corr)
    if n == 0:
        return 0.0
    m = np.array([[v if v is not None else 0.0 for v in row] for row in corr], dtype=float)
    eig = np.clip(np.linalg.eigvalsh(m), 0.0, None)
    total = float(eig.sum())
    squares = float((eig**2).sum())
    return total * total / squares if squares > 0 else 0.0


def sharpe(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    arr = np.array(returns, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd < FLAT:
        return None
    return float(arr.mean() / sd * math.sqrt(TRADING_DAYS))


def book(series: Sequence[dict[date, float]], groups: Sequence[Sequence[int]]) -> dict[date, float]:
    """Equal weight across families, equal within a family, rebalanced daily.

    On each day only members with a return that day take part, and only
    families with at least one such member. A day no member traded is left out.
    """
    days = sorted(set().union(*(s.keys() for s in series))) if series else []
    out: dict[date, float] = {}
    for day in days:
        family_returns = []
        for group in groups:
            present = [series[i][day] for i in group if day in series[i]]
            if present:
                family_returns.append(sum(present) / len(present))
        if family_returns:
            out[day] = sum(family_returns) / len(family_returns)
    return out


def _round(value: float | None, places: int = 3) -> float | None:
    return None if value is None else round(value, places)


def build(
    series: Sequence[Series],
    market: dict[date, float] | None = None,
    *,
    join_at: float = JOIN_AT,
    min_overlap: int = MIN_OVERLAP,
) -> dict[str, Any]:
    """The whole map as one JSON-ready dictionary."""
    names = [s.strategy_id for s in series]
    raw = [s.returns for s in series]
    corr = matrix(raw, min_overlap=min_overlap)
    groups = families(corr, join_at=join_at)
    out: dict[str, Any] = {
        "strategies": [
            {
                "strategy_id": s.strategy_id,
                "configuration": s.configuration,
                "days": len(s.returns),
                "first_day": min(s.returns).isoformat(),
                "last_day": max(s.returns).isoformat(),
                "sharpe": _round(sharpe(list(s.returns.values()))),
                "beta_to_nifty": _round(beta(s.returns, market)) if market else None,
            }
            for s in series
        ],
        "join_at": join_at,
        "min_overlap": min_overlap,
        "correlation": [[_round(v) for v in row] for row in corr],
        "families": [[names[i] for i in g] for g in groups],
        "effective_count": round(effective_count(corr), 2),
        "average_correlation": _round(_average_off_diagonal(corr)),
    }
    whole = book(raw, groups)
    out["book"] = {
        "rule": "equal weight across families, equal within a family; fixed before any result",
        "days": len(whole),
        "sharpe": _round(sharpe(list(whole.values()))),
        "is_a_candidate": False,
    }
    if market:
        hedged_series = [hedged(r, market) for r in raw]
        kept = [i for i, h in enumerate(hedged_series) if h is not None]
        h_list = [hedged_series[i] or {} for i in kept]
        h_corr = matrix(h_list, min_overlap=min_overlap)
        h_groups = families(h_corr, join_at=join_at)
        h_book = book(h_list, h_groups)
        out["hedged"] = {
            "strategies": [names[i] for i in kept],
            "correlation": [[_round(v) for v in row] for row in h_corr],
            "families": [[names[kept[i]] for i in g] for g in h_groups],
            "effective_count": round(effective_count(h_corr), 2),
            "average_correlation": _round(_average_off_diagonal(h_corr)),
            "sharpe": {
                names[kept[i]]: _round(sharpe(list(h.values()))) for i, h in enumerate(h_list)
            },
            "book_sharpe": _round(sharpe(list(h_book.values()))),
            "note": "full-sample beta, no futures cost: an upper bound (S-056)",
        }
    return out


def _average_off_diagonal(corr: Sequence[Sequence[float | None]]) -> float | None:
    values = [v for i, row in enumerate(corr) for j, v in enumerate(row) if i < j and v is not None]
    return sum(values) / len(values) if values else None


def nifty_returns(
    loader: Callable[[], list[tuple[date, float]]] | None = None,
) -> dict[date, float]:
    """NIFTYBEES daily returns from the panel, chained across its split."""
    if loader is None:
        from eulerlab.benchmark import _nifty_closes

        loader = _nifty_closes
    closes = loader()
    return {
        day: level / before - 1.0 for (_, before), (day, level) in pairwise(closes) if before > 0
    }


def render(result: dict[str, Any]) -> str:
    """The plain-text page `make strategy-map` prints."""
    lines = [
        f"Strategies read: {len(result['strategies'])}. "
        f"Families at correlation >= {result['join_at']}: {len(result['families'])}. "
        f"Independent bets (participation ratio): {result['effective_count']}.",
        f"Average pairwise correlation: {result['average_correlation']}. "
        f"Equal-weight book Sharpe: {result['book']['sharpe']} "
        f"(descriptive only; not a gate candidate).",
    ]
    hedged_part = result.get("hedged")
    if hedged_part:
        lines.append(
            f"After taking out Nifty: {len(hedged_part['families'])} families, "
            f"{hedged_part['effective_count']} independent bets, average correlation "
            f"{hedged_part['average_correlation']}, book Sharpe {hedged_part['book_sharpe']} "
            f"({hedged_part['note']})."
        )
    lines.append("")
    for number, family in enumerate(result["families"], start=1):
        lines.append(f"Family {number} ({len(family)}): {', '.join(family)}")
    lines.append("")
    lines.append(f"{'strategy':40} {'days':>5} {'sharpe':>7} {'beta':>6}")
    for row in result["strategies"]:
        lines.append(
            f"{row['strategy_id'][:40]:40} {row['days']:>5} "
            f"{row['sharpe'] if row['sharpe'] is not None else '-':>7} "
            f"{row['beta_to_nifty'] if row['beta_to_nifty'] is not None else '-':>6}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--root", type=Path, default=WORKSPACES)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--join-at", type=float, default=JOIN_AT)
    args = parser.parse_args(argv)
    series = collect(args.root)
    if len(series) < 2:
        print(f"Only {len(series)} stored equity reports with {MIN_DAYS}+ days; nothing to map.")
        return 1
    result = build(series, nifty_returns() or None, join_at=args.join_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(render(result))
    print(f"\nWritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
