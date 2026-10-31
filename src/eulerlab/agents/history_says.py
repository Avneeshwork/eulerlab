"""What history says: past days that looked like today, and what followed (ADR-109).

The outside view research 134 recommends. A past trading day matches today
when three fixed conditions read the same (`config/history_setup.yaml`):

1. Nifty 50 above or below its 200-day average;
2. India VIX low, middle or high against its previous 251 closes;
3. large caps leading, small caps leading, or neither, over 21 sessions.

For each match, Nifty 50's return over the next 1, 5 and 20 sessions. Each
horizon reports the median, the share of times it went up, the worst 10% and
how many matching days and separate episodes (runs of consecutive matching
days) it rests on. Below `min_matches` it says too few and gives no numbers.

**No look-ahead.** A day's conditions use only closes up to and including that
day, which were known at its close; returns start from that close. A test
changes every later close and checks the day's conditions do not move.

**Your books in this kind of market.** For each running book, its strategy's
stored backtest return on the session after each matching day.

History, not a forecast. Nothing here logs a trial, reads the holdout, or
touches the gate: it evaluates no strategy configuration, it reads the market's
own past and the backtests already stored.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from eulerlab.config import CONFIG_DIR

LABEL = "History, not a forecast."


class Setup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: str
    trend_window: int
    vix_window: int
    vix_low_below: float
    vix_high_from: float
    gap_sessions: int
    gap_points: float
    horizons: list[int]
    min_matches: int


def setup(config_dir: Path | None = None) -> Setup:
    path = (config_dir or CONFIG_DIR) / "history_setup.yaml"
    return Setup.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@dataclass(frozen=True)
class Day:
    day: date
    nifty: float
    vix: float
    small: float


def align(
    nifty: Mapping[date, float], vix: Mapping[date, float], small: Mapping[date, float], start: date
) -> list[Day]:
    """Days on which all three closes are held, oldest first."""
    days = sorted(d for d in nifty if d >= start and d in vix and d in small)
    return [Day(d, nifty[d], vix[d], small[d]) for d in days]


def state(days: Sequence[Day], i: int, s: Setup) -> tuple[str, str, str] | None:
    """The three condition words on day `i`, from days[0..i] only. None while warming up."""
    if i < max(s.trend_window - 1, s.vix_window, s.gap_sessions):
        return None
    today = days[i]
    average = sum(d.nifty for d in days[i - s.trend_window + 1 : i + 1]) / s.trend_window
    trend = "above its 200-day" if today.nifty > average else "below its 200-day"
    past = sorted(d.vix for d in days[i - s.vix_window : i])
    pct = 100.0 * bisect.bisect_left(past, today.vix) / len(past)
    vix = "low" if pct < s.vix_low_below else ("high" if pct >= s.vix_high_from else "middle")
    back = days[i - s.gap_sessions]
    gap = ((today.nifty / back.nifty) - (today.small / back.small)) * 100
    lead = (
        "large caps lead"
        if gap > s.gap_points
        else ("small caps lead" if gap < -s.gap_points else "neither leads")
    )
    return trend, vix, lead


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _episodes(indexes: Sequence[int]) -> int:
    return sum(1 for k, i in enumerate(indexes) if k == 0 or i != indexes[k - 1] + 1)


def base_rates(days: Sequence[Day], s: Setup) -> dict[str, Any]:
    """Today's setup, the matching past days, and what Nifty did after them."""
    if len(days) < 2:
        return {"available": False, "reason": "index history not held"}
    last = len(days) - 1
    now = state(days, last, s)
    if now is None:
        return {"available": False, "reason": "not enough index history"}
    matches = [i for i in range(last) if state(days, i, s) == now]
    out: dict[str, Any] = {
        "available": True,
        "as_of": days[last].day.isoformat(),
        "since": days[0].day.isoformat(),
        "setup": {
            "trend": now[0],
            "volatility": f"India VIX {now[1]} against its past year",
            "leadership": now[2],
        },
        "matches": len(matches),
        "episodes": _episodes(matches),
        "label": LABEL,
        "horizons": [],
        "match_days": [days[i].day.isoformat() for i in matches],
    }
    for h in s.horizons:
        usable = [i for i in matches if i + h <= last]
        returns = [days[i + h].nifty / days[i].nifty - 1 for i in usable]
        row: dict[str, Any] = {"sessions": h, "n": len(returns), "episodes": _episodes(usable)}
        if len(returns) >= s.min_matches:
            row.update(
                median=round(_quantile(returns, 0.5), 5),
                up=round(sum(1 for r in returns if r > 0) / len(returns), 3),
                worst_10=round(_quantile(returns, 0.1), 5),
            )
        else:
            row["too_few"] = True
        out["horizons"].append(row)
    return out


def describe(rates: Mapping[str, Any], min_matches: int) -> list[str]:
    """Plain lines for the brief."""
    if not rates.get("available"):
        return [f"Not available: {rates.get('reason')}."]
    st = rates["setup"]
    lines = [
        f"Today: Nifty {st['trend']}; {st['volatility']}; {st['leadership']} (data to {rates['as_of']}).",
        f"Matching days since {rates['since']}: {rates['matches']}, in {rates['episodes']} separate episodes.",
    ]
    for h in rates["horizons"]:
        span = "next session" if h["sessions"] == 1 else f"next {h['sessions']} sessions"
        if h.get("too_few"):
            lines.append(
                f"{span.capitalize()}: only {h['n']} matching days (fewer than {min_matches}); too few to lean on."
            )
        else:
            lines.append(
                f"{span.capitalize()}: Nifty's median {h['median'] * 100:+.2f}%, up {h['up'] * 100:.0f}% of the time, "
                f"worst 10% {h['worst_10'] * 100:+.2f}% or lower ({h['n']} days, {h['episodes']} episodes)."
            )
    lines.append(
        f"{LABEL} Conditions are fixed in config/history_setup.yaml, not tuned to results."
    )
    return lines


# --- your books in this kind of market -----------------------------------------------------------


def longest_backtest(folder: Path) -> dict[str, float]:
    """Daily returns by date from the strategy's longest stored backtest, or {}."""
    best: list[tuple[str, float]] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            equity = json.loads(path.read_text(encoding="utf-8")).get("equity") or {}
        except (OSError, ValueError):
            continue
        pairs = list(zip(equity.get("days") or [], equity.get("values") or [], strict=False))
        if len(pairs) > len(best):
            best = [(str(d), float(v)) for d, v in pairs]
    return {
        best[k][0]: best[k][1] / best[k - 1][1] - 1
        for k in range(1, len(best))
        if best[k - 1][1] > 0
    }


def books_in_this_market(
    books: Sequence[Mapping[str, Any]],
    match_days: Sequence[str],
    trading_days: Sequence[str],
    backtests: Mapping[str, Mapping[str, float]],
    min_matches: int,
) -> list[str]:
    """Each running book's backtest return on the session after each matching day."""
    following = {}
    position = {d: k for k, d in enumerate(trading_days)}
    for d in match_days:
        k = position.get(d)
        if k is not None and k + 1 < len(trading_days):
            following[d] = trading_days[k + 1]
    lines = []
    seen: set[str] = set()
    for b in books:
        if b.get("status") != "active" or b.get("strategy") in seen:
            continue
        name = str(b.get("strategy"))
        seen.add(name)
        returns = backtests.get(name) or {}
        if not returns:
            lines.append(
                f"{name}: its backtest's daily returns are not saved, so there is nothing to compare."
            )
            continue
        hits = [returns[nxt] for nxt in following.values() if nxt in returns]
        if len(hits) < min_matches:
            lines.append(
                f"{name}: only {len(hits)} of its backtest days follow a matching day; too few to lean on."
            )
            continue
        ordered = sorted(hits)
        median = ordered[len(ordered) // 2]
        up = sum(1 for r in hits if r > 0) / len(hits)
        lines.append(
            f"{name}: in its backtest, the session after a day like today returned a median {median * 100:+.2f}%, "
            f"up {up * 100:.0f}% of the time ({len(hits)} days)."
        )
    return lines
