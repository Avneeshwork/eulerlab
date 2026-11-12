"""Twenty MFT-style stock scalps on 5-minute closes, at Zerodha MIS size (research 168, 169).

Pre-registered as H-0111 to H-0120 before any run. Every rule decides on a
5-minute close of research 161's snapshots (`make minute-six`) and fills at
the next minute's open. ₹5 lakh a trade (₹1 lakh of margin at Zerodha's 5x
MIS), at most ten open at once on ₹10 lakh of margin, flat by 15:10; cash
intraday charges plus 2 bps a side. Window 2021-11-01 to 2024-10-15, where
Nifty minutes exist.

- **H-0111** Nifty 15-minute burst of 0.25%: the two lagging high-beta stocks, 30 minutes.
- **H-0112** every half hour, fade the largest 30-minute residual (>= 1.5%), 30 minutes.
- **H-0113** an industry leader's 1% move in 15 minutes: its slowest peer, 30 minutes.
- **H-0114** 14:30: the five biggest movers (>= 2%) agreeing with the Nifty, to 15:10.
- **H-0115** a 2% gap whose first 15 minutes turn back: toward the previous close.
- **H-0116** a 1.5% drive 09:20-09:45 with the Nifty: follow to 11:15.
- **H-0117** midday break of the 09:20-11:30 range in the Nifty's direction, to 15:10.
- **H-0118** noon pullback in a 2.5% trend-day stock, to 15:10.
- **H-0119** idiosyncratic 1.2% five-minute drop in a large cap: buy, 20 minutes.
- **H-0120** break of the previous session's high (low) close in the Nifty's direction.

Research 169 (H-0121 to H-0130), written after 168's results: H-0118 at 13:30,
gap and go, relative strength at 11:00, tight-range break, gap reclaimed,
yesterday's winner that holds, Nifty V-rebound with high-beta stocks,
industry-breadth laggards, quiet-day fade, yesterday's winner after a dip.

`make mft-screen` writes `data/derived/mft_screen.json`.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import minute_six_screen as six
from eulerlab.intraday import screen_common as sc
from eulerlab.intraday import stock_fo_screen as fo

OUT = data_path("derived/mft_screen.json")
INDEX = data_path("derived/index_history.jsonl")
TRADE = 500_000.0
"""₹1 lakh of margin at Zerodha's 5x MIS leverage (research 168)."""
MAX_OPEN = 10
CAPITAL = 1_000_000.0
"""Margin: ten ₹5 lakh positions at 5x."""
START = date(2021, 11, 1)
BETA_DAYS = 60
VALUE_DAYS = 20
EXIT = cs.EXIT
LATE = 5


def _k(minute: int) -> int:
    return six._k(minute)


@dataclass(frozen=True)
class Signal:
    day: date
    symbol: str
    direction: int
    decided: int
    """The checkpoint minute whose close decided the trade."""
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    reason: str
    rank: float = 0.0
    """Larger first when a rule caps how many it takes."""


@dataclass
class Market:
    snaps: Mapping[str, Mapping[date, six.Snap]]
    sessions: list[date]
    nifty: Mapping[date, Sequence[float]]
    """Nifty 50 close at each minute after 09:15."""
    nifty_prev: Mapping[date, float]
    beta: Mapping[tuple[str, date], float]
    liquid: Mapping[date, list[str]]
    """Symbols by 20-session mean traded value, largest first."""
    industry: Mapping[str, str]

    previous: Mapping[date, date]
    """Each session's previous session in the snapshots."""
    nifty_close: Mapping[date, float] = field(default_factory=dict)
    """The Nifty 50's official close by day (research 170)."""

    def prev(self, day: date) -> date | None:
        return self.previous.get(day)


# --- building the market -------------------------------------------------------------


def _official_closes(name: str = "Nifty 50", path: Path = INDEX) -> dict[date, float]:
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            bar = row["indices"].get(name) or {}
            if bar.get("c"):
                out[date.fromisoformat(row["d"])] = float(bar["c"])
    return out


def betas(
    snaps: Mapping[str, Mapping[date, six.Snap]],
    sessions: Sequence[date],
    index_close: Mapping[date, float],
) -> dict[tuple[str, date], float]:
    """Each stock's beta to the Nifty over the 60 sessions before each day."""
    market = {
        b: index_close[b] / index_close[a] - 1.0
        for a, b in pairwise(sessions)
        if a in index_close and b in index_close
    }
    out: dict[tuple[str, date], float] = {}
    for symbol, days in snaps.items():
        pairs: list[tuple[date, float, float]] = []
        for a, b in pairwise(sessions):
            if a in days and b in days and b in market and days[a].last_close > 0:
                pairs.append((b, days[b].last_close / days[a].last_close - 1.0, market[b]))
        for i in range(BETA_DAYS, len(pairs)):
            window = pairs[i - BETA_DAYS : i]
            xs = [m for _, _, m in window]
            ys = [r for _, r, _ in window]
            var = statistics.pvariance(xs)
            if var > 0:
                mx, my = statistics.fmean(xs), statistics.fmean(ys)
                cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / len(xs)
                out[(symbol, pairs[i][0])] = cov / var
    return out


def liquidity(
    snaps: Mapping[str, Mapping[date, six.Snap]], sessions: Sequence[date]
) -> dict[date, list[str]]:
    """Symbols by mean traded value over the 20 sessions before each day (15 needed)."""
    out: dict[date, list[str]] = {}
    for i in range(VALUE_DAYS, len(sessions)):
        before = sessions[i - VALUE_DAYS : i]
        day = sessions[i]
        scored = []
        for symbol, days in snaps.items():
            if day not in days:
                continue
            values = [days[d].value for d in before if d in days]
            if len(values) >= 15:
                scored.append((-statistics.fmean(values), symbol))
        out[day] = [symbol for _, symbol in sorted(scored)]
    return out


def build() -> Market:
    from eulerlab.features import company

    snaps, window = fo.load_snaps()
    index_days = {d.day: d.close for d in five.load_index()}
    sessions = [d for d in window if d >= START and d in index_days]
    official = _official_closes()
    prev: dict[date, float] = {}
    ordered = sorted(official)
    for i, d in enumerate(ordered[1:], 1):
        prev[d] = official[ordered[i - 1]]
    industry = {s: c.industry for s, c in company.load_digest().items() if c.industry}
    all_sessions = [d for d in window if d in official]
    return Market(
        snaps=snaps,
        sessions=sessions,
        nifty=index_days,
        nifty_prev=prev,
        beta=betas(snaps, all_sessions, official),
        liquid=liquidity(snaps, window),
        industry=industry,
        previous={b: a for a, b in pairwise(window)},
        nifty_close=official,
    )


# --- fills ---------------------------------------------------------------------------


def entry_at(s: six.Snap, minute: int) -> tuple[int, float] | None:
    """The open of the first traded minute after checkpoint `minute`, before the exit."""
    if minute >= EXIT:
        return None
    k = _k(minute)
    if s.fill_minutes[k] < 0:
        return None
    return int(s.fill_minutes[k]), float(s.fills[k])


def exit_at(s: six.Snap, minute: int) -> tuple[int, float]:
    """The fill after checkpoint `minute`, or the 15:10 exit."""
    if minute < EXIT:
        found = entry_at(s, minute)
        if found is not None:
            return found
    return s.exit_minute, s.exit


def held(
    s: six.Snap,
    day: date,
    symbol: str,
    direction: int,
    decided: int,
    *,
    hold: int | None = None,
    stop: Callable[[float], bool] | None = None,
    target: Callable[[float], bool] | None = None,
    delay: int = 0,
    rank: float = 0.0,
) -> Signal | None:
    """A trade decided at `decided` (filled `delay` minutes later), exited after
    `hold` minutes, at the first close that hits `stop` or `target`, or at 15:10."""
    start = decided + delay
    opened = entry_at(s, start)
    if opened is None:
        return None
    last = min(start + hold, EXIT) if hold is not None else EXIT
    for m in range(start + six.STEP, last, six.STEP):
        close = s.closes[_k(m)]
        if stop is not None and stop(close):
            mm, px = exit_at(s, m)
            return Signal(day, symbol, direction, decided, *opened, mm, px, "stop", rank)
        if target is not None and target(close):
            mm, px = exit_at(s, m)
            return Signal(day, symbol, direction, decided, *opened, mm, px, "target", rank)
    mm, px = exit_at(s, last)
    if mm <= opened[0]:
        return None
    return Signal(day, symbol, direction, decided, *opened, mm, px, "time", rank)


def _move(s: six.Snap, a: int, b: int) -> float:
    return s.closes[_k(b)] / s.closes[_k(a)] - 1.0


def _nifty_move(mk: Market, day: date, a: int, b: int) -> float:
    n = mk.nifty[day]
    return n[b] / n[a] - 1.0


def _pct_from_prev(mk: Market, symbol: str, day: date, m: int) -> float | None:
    p = mk.prev(day)
    if p is None:
        return None
    before = mk.snaps[symbol].get(p)
    s = mk.snaps[symbol].get(day)
    if before is None or s is None or before.last_close <= 0:
        return None
    return s.closes[_k(m)] / before.last_close - 1.0


def _nifty_day(mk: Market, day: date, m: int) -> float | None:
    prev = mk.nifty_prev.get(day)
    return mk.nifty[day][m] / prev - 1.0 if prev else None


def _today(mk: Market, symbol: str, day: date) -> six.Snap | None:
    s = mk.snaps.get(symbol, {}).get(day)
    return s if s is not None and s.entry >= cs.MIN_PRICE else None


# --- the ten rules ---------------------------------------------------------------------


def h0111(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    names = mk.liquid.get(day, [])[:100]
    last_fired = -1000
    for m in range(20, 316, 5):
        r = _nifty_move(mk, day, m - 15, m)
        if abs(r) < 0.0025 or m - last_fired < 30:
            continue
        sign = 1 if r > 0 else -1
        pool = []
        for symbol in names:
            s = _today(mk, symbol, day)
            b = mk.beta.get((symbol, day))
            if s is None or b is None or b < 1.0:
                continue
            pool.append((sign * _move(s, m - 15, m), symbol, s))
        pool.sort(key=lambda x: (x[0], x[1]))
        fired = False
        for _, symbol, s in pool[:2]:
            sig = held(s, day, symbol, sign, m, hold=30, delay=delay)
            if sig:
                fired = True
                yield sig
        if fired:
            last_fired = m


def h0112(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    names = mk.liquid.get(day, [])[:100]
    for m in range(45, 316, 30):
        nm = _nifty_move(mk, day, m - 30, m)
        best: tuple[float, str, six.Snap, float] | None = None
        for symbol in names:
            s = _today(mk, symbol, day)
            b = mk.beta.get((symbol, day))
            if s is None or b is None:
                continue
            resid = _move(s, m - 30, m) - b * nm
            if best is None or (abs(resid), symbol) > (abs(best[0]), best[1]):
                best = (resid, symbol, s, b)
        if best is not None and abs(best[0]) >= 0.015:
            sig = held(best[2], day, best[1], -1 if best[0] > 0 else 1, m, hold=30, delay=delay)
            if sig:
                yield sig


def h0113(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    names = mk.liquid.get(day, [])[:200]
    groups: dict[str, list[str]] = defaultdict(list)
    for symbol in names:  # already by traded value, largest first
        if symbol in mk.industry and _today(mk, symbol, day) is not None:
            groups[mk.industry[symbol]].append(symbol)
    last: dict[str, int] = {}
    for m in range(30, 316, 15):
        for group, members in sorted(groups.items()):
            if len(members) < 4 or m - last.get(group, -1000) < 60:
                continue
            leader = members[0]
            r = _move(mk.snaps[leader][day], m - 15, m)
            if abs(r) < 0.01:
                continue
            sign = 1 if r > 0 else -1
            peers = sorted((sign * _move(mk.snaps[p][day], m - 15, m), p) for p in members[1:])
            symbol = peers[0][1]
            sig = held(mk.snaps[symbol][day], day, symbol, sign, m, hold=30, delay=delay)
            if sig:
                last[group] = m
                yield sig


def h0114(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    m = 315
    nd = _nifty_day(mk, day, m)
    if nd is None or abs(nd) < 0.003:
        return
    sign = 1 if nd > 0 else -1
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        r = _pct_from_prev(mk, symbol, day, m)
        if r is not None and sign * r >= 0.02 and _today(mk, symbol, day) is not None:
            pool.append((-abs(r), symbol))
    for _, symbol in sorted(pool)[:5]:
        sig = held(mk.snaps[symbol][day], day, symbol, sign, m, delay=delay)
        if sig:
            yield sig


def h0115(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    p = mk.prev(day)
    if p is None:
        return
    pool = []
    for symbol in mk.liquid.get(day, [])[:200]:
        s, before = _today(mk, symbol, day), mk.snaps[symbol].get(p)
        if s is None or before is None or before.last_close <= 0:
            continue
        prev_close, first = before.last_close, s.closes[_k(5)]
        gap = first / prev_close - 1.0
        now = s.closes[_k(15)]
        between = min(prev_close, first) < now < max(prev_close, first)
        if abs(gap) >= 0.02 and between:
            pool.append((-abs(gap), symbol, s, prev_close, gap))
    for _, symbol, s, prev_close, gap in sorted(pool, key=lambda x: (x[0], x[1]))[:10]:
        direction = -1 if gap > 0 else 1
        opened = entry_at(s, 15 + delay)
        if opened is None:
            continue
        entry = opened[1]

        def stop(c: float, e: float = entry, d: int = direction) -> bool:
            return d * (c / e - 1.0) <= -0.01

        def target(c: float, pc: float = prev_close, d: int = direction) -> bool:
            return d * (c - pc) >= 0

        sig = held(s, day, symbol, direction, 15, stop=stop, target=target, delay=delay)
        if sig:
            yield sig


def h0116(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    nm = _nifty_move(mk, day, 5, 30)
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        s = _today(mk, symbol, day)
        if s is None:
            continue
        r = _move(s, 5, 30)
        if abs(r) >= 0.015 and r * nm > 0:
            pool.append((-abs(r), symbol, s, 1 if r > 0 else -1))
    for _, symbol, s, sign in sorted(pool, key=lambda x: (x[0], x[1]))[:5]:
        sig = held(s, day, symbol, sign, 30, hold=90, delay=delay)
        if sig:
            yield sig


def h0117(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    n = mk.nifty[day]
    for symbol in mk.liquid.get(day, [])[:100]:
        s = _today(mk, symbol, day)
        if s is None:
            continue
        morning = [s.closes[_k(m)] for m in range(5, 136, 5)]
        high, low = max(morning), min(morning)
        middle = (high + low) / 2
        for m in range(140, 256, 5):
            c = s.closes[_k(m)]
            up, down = c > high and n[m] > n[5], c < low and n[m] < n[5]
            if not (up or down):
                continue
            sign = 1 if up else -1

            def stop(x: float, mid: float = middle, d: int = sign) -> bool:
                return d * (x - mid) < 0

            sig = held(s, day, symbol, sign, m, stop=stop, delay=delay, rank=-m)
            if sig:
                yield sig
            break


def _pullback(mk: Market, day: date, m: int, delay: int) -> Iterator[Signal]:
    """H-0118 / H-0121: a 2.5% trend-day stock 0.5% off its extreme at minute `m`."""
    nd = _nifty_day(mk, day, m)
    if nd is None or nd == 0:
        return
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        s = _today(mk, symbol, day)
        r = _pct_from_prev(mk, symbol, day, m)
        if s is None or r is None:
            continue
        closes = [s.closes[_k(x)] for x in range(5, m + 1, 5)]
        now = closes[-1]
        if r >= 0.025 and nd > 0 and now <= 0.995 * max(closes):
            pool.append((-abs(r), symbol, s, 1))
        elif r <= -0.025 and nd < 0 and now >= 1.005 * min(closes):
            pool.append((-abs(r), symbol, s, -1))
    for _, symbol, s, sign in sorted(pool, key=lambda x: (x[0], x[1]))[:10]:
        sig = held(s, day, symbol, sign, m, delay=delay)
        if sig:
            yield sig


def h0118(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    return _pullback(mk, day, 165, delay)


def h0119(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    for symbol in mk.liquid.get(day, [])[:50]:
        s = _today(mk, symbol, day)
        if s is None:
            continue
        for m in range(15, 336, 5):
            if _move(s, m - 5, m) <= -0.012 and _nifty_move(mk, day, m - 5, m) > -0.002:
                sig = held(s, day, symbol, 1, m, hold=20, delay=delay)
                if sig:
                    yield sig
                break


def h0120(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    p = mk.prev(day)
    if p is None:
        return
    for symbol in mk.liquid.get(day, [])[:100]:
        s, before = _today(mk, symbol, day), mk.snaps[symbol].get(p)
        if s is None or before is None:
            continue
        top, bottom = max(before.closes), min(before.closes)
        for m in range(45, 286, 5):
            c, nd = s.closes[_k(m)], _nifty_day(mk, day, m)
            if nd is None:
                break
            up, down = c > top and nd > 0, c < bottom and nd < 0
            if not (up or down):
                continue
            sign, level = (1, top) if up else (-1, bottom)

            def stop(x: float, lv: float = level, d: int = sign) -> bool:
                return d * (x / lv - 1.0) <= -0.005

            sig = held(s, day, symbol, sign, m, stop=stop, delay=delay, rank=-m)
            if sig:
                yield sig
            break


# --- research 169: ten more ------------------------------------------------------------


def h0121(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    return _pullback(mk, day, 255, delay)


def _gaps(mk: Market, day: date, size: float) -> list[tuple[float, str, six.Snap, float, float]]:
    """(-|gap|, symbol, snap, previous close, gap) among the 200 most traded, largest first."""
    p = mk.prev(day)
    if p is None:
        return []
    out = []
    for symbol in mk.liquid.get(day, [])[:200]:
        s, before = _today(mk, symbol, day), mk.snaps[symbol].get(p)
        if s is None or before is None or before.last_close <= 0:
            continue
        gap = s.closes[_k(5)] / before.last_close - 1.0
        if abs(gap) >= size:
            out.append((-abs(gap), symbol, s, before.last_close, gap))
    return sorted(out, key=lambda x: (x[0], x[1]))


def h0122(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    nifty_gap = _nifty_day(mk, day, 5)
    if nifty_gap is None or nifty_gap == 0:
        return
    taken = 0
    for _, symbol, s, _, gap in _gaps(mk, day, 0.02):
        first = s.closes[_k(5)]
        if gap * nifty_gap <= 0 or (s.closes[_k(15)] - first) * gap <= 0:
            continue
        sign = 1 if gap > 0 else -1

        def stop(c: float, f: float = first, d: int = sign) -> bool:
            return d * (c - f) < 0

        sig = held(s, day, symbol, sign, 15, stop=stop, delay=delay)
        if sig:
            taken += 1
            yield sig
        if taken >= 10:
            return


def h0123(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    m = 105
    nd = _nifty_day(mk, day, m)
    if nd is None or abs(nd) < 0.005:
        return
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        r = _pct_from_prev(mk, symbol, day, m)
        if r is not None and r * nd < 0 and abs(r) >= 0.01 and _today(mk, symbol, day):
            pool.append((-abs(r), symbol, 1 if r > 0 else -1))
    for _, symbol, sign in sorted(pool)[:5]:
        sig = held(mk.snaps[symbol][day], day, symbol, sign, m, delay=delay)
        if sig:
            yield sig


def h0124(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    taken = 0
    for symbol in mk.liquid.get(day, [])[:100]:
        s = _today(mk, symbol, day)
        move = _pct_from_prev(mk, symbol, day, 60)
        if s is None or move is None or abs(move) < 0.015:
            continue
        box = [s.closes[_k(m)] for m in range(60, 121, 5)]
        high, low = max(box), min(box)
        if (high - low) / low >= 0.004:
            continue
        sign = 1 if move > 0 else -1
        for m in range(125, 286, 5):
            c = s.closes[_k(m)]
            if (sign > 0 and c > high) or (sign < 0 and c < low):

                def stop(x: float, hi: float = high, lo: float = low, d: int = sign) -> bool:
                    return x < lo if d > 0 else x > hi

                sig = held(s, day, symbol, sign, m, stop=stop, delay=delay)
                if sig:
                    taken += 1
                    yield sig
                break
        if taken >= 10:
            return


def h0125(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    found = []
    for _, symbol, s, prev_close, gap in _gaps(mk, day, 0.015):
        first = s.closes[_k(5)]
        for m in range(30, 226, 5):
            c = s.closes[_k(m)]
            if (gap > 0 and c < prev_close) or (gap < 0 and c > prev_close):
                sign = -1 if gap > 0 else 1
                halfway = (first + prev_close) / 2

                def stop(x: float, h: float = halfway, d: int = sign) -> bool:
                    return x > h if d < 0 else x < h

                sig = held(s, day, symbol, sign, m, stop=stop, delay=delay, rank=-m)
                if sig:
                    found.append(sig)
                break
    yield from sorted(found, key=lambda x: (x.entry_minute, x.symbol))[:10]


def _yesterday(mk: Market, symbol: str, day: date) -> tuple[float, float] | None:
    """(yesterday's close-to-close return, yesterday's close)."""
    p = mk.prev(day)
    pp = mk.prev(p) if p else None
    if p is None or pp is None:
        return None
    a, b = mk.snaps[symbol].get(pp), mk.snaps[symbol].get(p)
    if a is None or b is None or a.last_close <= 0:
        return None
    return b.last_close / a.last_close - 1.0, b.last_close


def _stop_pct(entry: float, sign: int, pct: float) -> Callable[[float], bool]:
    return lambda c: sign * (c / entry - 1.0) <= -pct


def h0126(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        s, y = _today(mk, symbol, day), _yesterday(mk, symbol, day)
        if s is None or y is None or abs(y[0]) < 0.02:
            continue
        sign = 1 if y[0] > 0 else -1
        first, now = s.closes[_k(5)], s.closes[_k(15)]
        if sign * (first / y[1] - 1.0) >= 0.005 and sign * (now - first) > 0:
            pool.append((-abs(y[0]), symbol, s, sign))
    for _, symbol, s, sign in sorted(pool, key=lambda x: (x[0], x[1]))[:10]:
        opened = entry_at(s, 15 + delay)
        if opened is None:
            continue
        sig = held(s, day, symbol, sign, 15, stop=_stop_pct(opened[1], sign, 0.01), delay=delay)
        if sig:
            yield sig


def h0127(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    n = mk.nifty[day]
    low, low_at = n[5], 5
    for m in range(5, 166, 5):
        if n[m] < low:
            low, low_at = n[m], m
        if m >= 30 and m > low_at and low <= n[5] * (1 - 0.006) and n[m] >= low * 1.003:
            pool = sorted(
                (-(mk.beta.get((sym, day)) or -9.0), sym)
                for sym in mk.liquid.get(day, [])[:100]
                if _today(mk, sym, day) is not None and (sym, day) in mk.beta
            )
            for _, symbol in pool[:3]:
                sig = held(mk.snaps[symbol][day], day, symbol, 1, m, delay=delay)
                if sig:
                    yield sig
            return


def h0128(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    m = 75
    groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for symbol in mk.liquid.get(day, [])[:200]:
        r = _pct_from_prev(mk, symbol, day, m)
        if symbol in mk.industry and r is not None and _today(mk, symbol, day):
            groups[mk.industry[symbol]].append((symbol, r))
    pool = []
    for _, members in sorted(groups.items()):
        if len(members) < 5:
            continue
        for sign in (1, -1):
            share = sum(1 for _, r in members if sign * r >= 0.01) / len(members)
            if share >= 0.7:
                pool += [(sym, sign) for sym, r in members if 0 <= sign * r <= 0.005]
    for symbol, sign in sorted(pool)[:10]:
        sig = held(mk.snaps[symbol][day], day, symbol, sign, m, delay=delay)
        if sig:
            yield sig


def h0129(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    n = mk.nifty[day]
    morning = [n[m] for m in range(5, 136, 5)]
    if (max(morning) - min(morning)) / min(morning) >= 0.005:
        return
    found = []
    for symbol in mk.liquid.get(day, [])[:100]:
        s = _today(mk, symbol, day)
        if s is None:
            continue
        first = s.closes[_k(5)]
        for m in range(135, 286, 5):
            move = s.closes[_k(m)] / first - 1.0
            if abs(move) >= 0.015:
                sig = held(s, day, symbol, -1 if move > 0 else 1, m, hold=30, delay=delay)
                if sig:
                    found.append(sig)
                break
    yield from sorted(found, key=lambda x: (x.entry_minute, x.symbol))[:10]


def h0130(mk: Market, day: date, delay: int = 0) -> Iterator[Signal]:
    m = 45
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        s, y = _today(mk, symbol, day), _yesterday(mk, symbol, day)
        if s is None or y is None or abs(y[0]) < 0.03:
            continue
        sign = 1 if y[0] > 0 else -1
        if sign * (s.closes[_k(m)] / y[1] - 1.0) <= -0.01:
            pool.append((-abs(y[0]), symbol, s, sign))
    for _, symbol, s, sign in sorted(pool, key=lambda x: (x[0], x[1]))[:10]:
        opened = entry_at(s, m + delay)
        if opened is None:
            continue
        sig = held(s, day, symbol, sign, m, stop=_stop_pct(opened[1], sign, 0.01), delay=delay)
        if sig:
            yield sig


RULES: dict[str, tuple[str, Callable[..., Iterator[Signal]]]] = {
    "H-0111": ("mft_nifty_burst_laggards", h0111),
    "H-0112": ("mft_residual_reversal_30m", h0112),
    "H-0113": ("mft_industry_leader_laggard", h0113),
    "H-0114": ("mft_late_day_momentum", h0114),
    "H-0115": ("mft_gap_fade_15m_turn", h0115),
    "H-0116": ("mft_opening_drive", h0116),
    "H-0117": ("mft_midday_range_break", h0117),
    "H-0118": ("mft_noon_trend_pullback", h0118),
    "H-0119": ("mft_idiosyncratic_drop_buy", h0119),
    "H-0120": ("mft_prior_day_break", h0120),
    "H-0121": ("mft_afternoon_trend_pullback", h0121),
    "H-0122": ("mft_gap_and_go", h0122),
    "H-0123": ("mft_relative_strength_1100", h0123),
    "H-0124": ("mft_tight_range_break", h0124),
    "H-0125": ("mft_gap_reclaimed", h0125),
    "H-0126": ("mft_yesterday_winner_holds", h0126),
    "H-0127": ("mft_nifty_v_rebound_beta", h0127),
    "H-0128": ("mft_industry_breadth_laggards", h0128),
    "H-0129": ("mft_quiet_day_fade", h0129),
    "H-0130": ("mft_yesterday_winner_dip", h0130),
}
BATCH_168 = tuple(f"H-0{n}" for n in range(111, 121))
BATCH_169 = tuple(f"H-0{n}" for n in range(121, 131))


# --- the book --------------------------------------------------------------------------


def book(signals: Sequence[Signal]) -> list[Signal]:
    """At most ten open at once and one position per stock, in order of entry;
    signals entering in the same minute keep their rule's order."""
    out: list[Signal] = []
    by_day: dict[date, list[Signal]] = defaultdict(list)
    for sig in signals:
        by_day[sig.day].append(sig)
    for day in sorted(by_day):
        open_: list[Signal] = []
        for sig in sorted(by_day[day], key=lambda x: x.entry_minute):
            open_ = [o for o in open_ if o.exit_minute > sig.entry_minute]
            if len(open_) >= MAX_OPEN or any(o.symbol == sig.symbol for o in open_):
                continue
            open_.append(sig)
            out.append(sig)
    return out


def trades_for(mk: Market, hypothesis: str, *, delay: int = 0) -> list[cs.Trade]:
    _, rule = RULES[hypothesis]
    signals = [sig for day in mk.sessions for sig in rule(mk, day, delay)]
    out = []
    for sig in book(signals):
        fill = five.Fill(
            sig.decided,
            sig.direction,
            sig.entry_minute,
            sig.entry,
            sig.exit_minute,
            sig.exit,
            sig.reason,
        )
        trade = five._trade(sig.symbol, sig.day, fill, sig.direction, TRADE)
        if trade:
            out.append(trade)
    return out


def evaluate(mk: Market, hypothesis: str) -> dict[str, Any]:
    run_id, _ = RULES[hypothesis]
    trades = trades_for(mk, hypothesis)
    run = cs.report(
        run_id,
        trades,
        mk.sessions,
        params={"notional": TRADE, "max_open": MAX_OPEN, "slippage_bps_per_side": cs.SLIPPAGE_BPS},
        capital=CAPITAL,
    )
    daily = [r for _, r in run["daily"]]
    middle = len(daily) // 2
    run["halves"] = {
        "first": sc.daily_stats(daily[:middle]),
        "second": sc.daily_stats(daily[middle:]),
    }
    run["hypothesis"] = hypothesis
    run["trades_a_day"] = round(len(trades) / len(mk.sessions), 2) if mk.sessions else 0
    run["costs_bps_a_trade"] = (
        round(sum(t.costs for t in trades) / sum(t.notional for t in trades) * 1e4, 2)
        if trades
        else None
    )
    run.pop("trade_log", None)
    return run


_MARKET: Market | None = None


def market() -> Market:
    global _MARKET
    if _MARKET is None:
        _MARKET = build()
    return _MARKET


def validation_run(hypothesis: str) -> IntradayRun:
    """Trades as screened and filled five minutes late, for the battery (ADR-139)."""
    from eulerlab.validation.intraday import IntradayRun

    mk = market()
    return IntradayRun(
        trades_for(mk, hypothesis), trades_for(mk, hypothesis, delay=LATE), mk.sessions, CAPITAL
    )


def run(output: Path = OUT) -> dict[str, Any]:
    mk = market()
    result = {
        "research": "168, 169",
        "spent_trials": 0,
        "window": [mk.sessions[0].isoformat(), mk.sessions[-1].isoformat()],
        "runs": [evaluate(mk, h) for h in RULES],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="mft-screen")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for one in run(args.output)["runs"]:
        years = {y: round(v["total_return"], 4) for y, v in one["net_by_year"].items()}
        pt = one["per_trade_bps"]
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades ({one['trades_a_day']}/day); "
            f"{pt['gross_mean']} gross, {pt['net_mean']} net bps (cost {one['costs_bps_a_trade']}); "
            f"net Sharpe {one['net']['sharpe']}; halves {one['halves']['first']['sharpe']} / "
            f"{one['halves']['second']['sharpe']}; {years}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
