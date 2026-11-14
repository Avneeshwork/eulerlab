"""Ten rules on non-price data: five swing, five intraday (research 172, H-0151 to H-0160).

Signals come from stock-option implied vols, results dates, SAST promoter
buys, NSE's participant-wise OI, NSE filings, India VIX and delivery; trades
are in NSE cash stocks or NIFTYBEES at 1x, ₹1 lakh a position (H-0154: the
whole ₹10 lakh in NIFTYBEES), at most ten open.

- **Swing** (delivery, long only): in at a session's 09:20 fill, out at the
  15:10 fill of the exit session, marked to market at each last close in
  between so a day's P&L lands on that day. Delivery charges plus 2 bps a
  side (26.2 bps a round trip).
- **Intraday**: 09:20 (H-0158: 09:30) to 15:10, 12.24 bps a round trip.

Same snapshots, liquidity ranking, betas and window as `mft_screen`
(research 168). Screen as research 170: both halves and 2x costs net positive.
`make other-data-screen` writes `data/derived/other_data_screen.json`.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from functools import cached_property, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import mft_screen as mft
from eulerlab.intraday import minute_six_screen as six
from eulerlab.intraday import onex_screen as onex
from eulerlab.intraday import screen_common as sc

OUT = data_path("derived/other_data_screen.json")
TRADE = 100_000.0
CAPITAL = 1_000_000.0
MAX_OPEN = 10
SLIPPAGE_BPS = 2.0
ETF = "NIFTYBEES"
PCTL_DAYS = 250
DELIVERY = data_path("derived/delivery.jsonl")
EARNINGS = data_path("derived/nse_earnings_announcements.jsonl")


@lru_cache(maxsize=1 << 20)  # pure, and the same fill recurs across a population (#167)
def delivery_fee(price: float, quantity: int, side: Side, day: date) -> float:
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=quantity,
        side=side,
        day=day,
        segment=Segment.EQUITY_DELIVERY,
    )


# --- a swing position, booked day by day ---------------------------------------------


@dataclass(frozen=True)
class Piece:
    """One day of a swing position: what the validation battery reads (`DayTrade`)."""

    symbol: str
    day: date
    gross: float
    costs: float


@dataclass(frozen=True)
class Swing:
    symbol: str
    entry_day: date
    exit_day: date
    quantity: int
    entry: float
    exit: float
    marks: tuple[tuple[date, float], ...]
    """(day, last close) for each session from entry to the one before exit."""

    @property
    def notional(self) -> float:
        return self.entry * self.quantity

    @property
    def gross_total(self) -> float:
        return (self.exit - self.entry) * self.quantity

    def costs_at(self, multiple: float = 1.0) -> tuple[float, float]:
        buy, sell = self._costs
        return buy * multiple, sell * multiple

    @cached_property
    def _costs(self) -> tuple[float, float]:
        """The buy and sell costs, computed once a position (#167)."""
        q = self.quantity
        buy = (
            delivery_fee(self.entry, q, Side.BUY, self.entry_day)
            + self.entry * q * SLIPPAGE_BPS / 1e4
        )
        sell = (
            delivery_fee(self.exit, q, Side.SELL, self.exit_day)
            + self.exit * q * SLIPPAGE_BPS / 1e4
        )
        return buy, sell

    def pieces(self) -> list[Piece]:
        buy, sell = self.costs_at()
        out: list[Piece] = []
        last = self.entry
        for i, (day, close) in enumerate(self.marks):
            out.append(
                Piece(self.symbol, day, (close - last) * self.quantity, buy if i == 0 else 0.0)
            )
            last = close
        if self.marks and self.marks[0][0] == self.exit_day:  # pragma: no cover
            raise ValueError("marks must stop before the exit session")
        out.append(
            Piece(
                self.symbol,
                self.exit_day,
                (self.exit - last) * self.quantity,
                sell + (0.0 if self.marks else buy),
            )
        )
        return out


def swing(
    snaps: Mapping[date, six.Snap],
    sessions: Sequence[date],
    symbol: str,
    entry_day: date,
    hold: int,
    notional: float = TRADE,
) -> Swing | None:
    """In at `entry_day`'s 09:20 fill, out at the 15:10 fill `hold` sessions later."""
    i = bisect.bisect_left(sessions, entry_day)
    if i >= len(sessions) or sessions[i] != entry_day or i + hold >= len(sessions):
        return None
    days = sessions[i : i + hold + 1]
    if any(d not in snaps for d in days):
        return None
    first, last = snaps[days[0]], snaps[days[-1]]
    if first.entry < cs.MIN_PRICE:
        return None
    quantity = int(notional / first.entry)
    if not quantity:
        return None
    marks = tuple((d, snaps[d].last_close) for d in days[:-1])
    return Swing(symbol, days[0], days[-1], quantity, first.entry, last.exit, marks)


def cap_swings(
    found: Sequence[tuple[date, float, str, Swing]], limit: int = MAX_OPEN
) -> list[Swing]:
    """At most `limit` open at once and one per stock, earliest entry first."""
    out: list[Swing] = []
    for _, _, _, s in sorted(found, key=lambda x: (x[0], x[1], x[2])):
        open_ = [o for o in out if o.exit_day >= s.entry_day]
        if len(open_) >= limit or any(o.symbol == s.symbol for o in open_):
            continue
        out.append(s)
    return out


# --- data ----------------------------------------------------------------------------


def participant_positions() -> dict[date, dict[str, dict[str, int]]]:
    """{day: {Client|DII|FII|Pro: {field: contracts}}} from NSE's participant-wise OI."""
    from eulerlab.ingest import landing_reader

    out: dict[date, dict[str, dict[str, int]]] = {}
    manifest = data_path("landing/nse/manifest.jsonl")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") != "participant_oi":
            continue
        day = date.fromisoformat(entry["trade_date"])
        if day > cs.DATA_END:
            continue
        try:
            text = landing_reader.read(f"nse/{entry['path']}", cache=True).decode(
                "utf-8-sig", "replace"
            )
        except FileNotFoundError:
            continue
        parsed = parse_participants(text)
        if parsed:
            out[day] = parsed
    return out


def parse_participants(text: str) -> dict[str, dict[str, int]]:
    lines = text.splitlines()
    header = next((i for i, x in enumerate(lines) if x.lstrip().startswith("Client Type")), None)
    if header is None:
        return {}
    reader = csv.reader(io.StringIO("\n".join(lines[header:])))
    names = [n.strip().strip("\t") for n in next(reader)]
    out: dict[str, dict[str, int]] = {}
    for row in reader:
        if not row or row[0].strip() not in {"Client", "DII", "FII", "Pro"}:
            continue
        values: dict[str, int] = {}
        for name, cell in zip(names[1:], row[1:], strict=False):
            try:
                values[name] = int(cell.strip().replace(",", "") or 0)
            except ValueError:
                continue
        out[row[0].strip()] = values
    return out


def net_futures(p: Mapping[str, int]) -> int:
    return p.get("Future Index Long", 0) - p.get("Future Index Short", 0)


def net_puts(p: Mapping[str, int]) -> int:
    return p.get("Option Index Put Long", 0) - p.get("Option Index Put Short", 0)


def percentile_rank(history: Sequence[float], value: float) -> float:
    return sum(1 for h in history if h < value) / len(history)


def delivery_ratios(
    path: Path = DELIVERY, *, since: date | None = None
) -> dict[str, dict[date, float]]:
    """{symbol: {day: delivery % / its previous 20-session mean}}; with `since`,
    only days after it are read (a paper book's holdout end)."""
    series: dict[str, list[tuple[date, float]]] = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            day = date.fromisoformat(row["d"])
            if since is not None and day <= since:
                continue
            for symbol, values in row["stocks"].items():
                if len(values) >= 3 and values[2] is not None:
                    series[symbol].append((day, float(values[2])))
    out: dict[str, dict[date, float]] = {}
    for symbol, rows in series.items():
        rows.sort()
        found = {}
        for i in range(20, len(rows)):
            mean = statistics.fmean(v for _, v in rows[i - 20 : i])
            if mean > 0:
                found[rows[i][0]] = rows[i][1] / mean
        out[symbol] = found
    return out


def results_times(path: Path = EARNINGS) -> dict[str, list[datetime]]:
    out: dict[str, list[datetime]] = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            out[row["symbol"]].append(datetime.fromisoformat(row["event_time"]))
    return {s: sorted(v) for s, v in out.items()}


# --- the context ---------------------------------------------------------------------


class Context:
    def __init__(self) -> None:
        from eulerlab.intraday import nse_reports_screen as rep
        from eulerlab.intraday import option_iv_screen as iv
        from eulerlab.intraday import research_screen as rs

        self.mk = mft.market()
        self.sessions = sorted({d for days in self.mk.snaps.values() for d in days})
        self.window = list(self.mk.sessions)
        self.options = iv.load_options_daily()
        self.participants = participant_positions()
        self.news = onex.load_news(set(self.mk.snaps))
        self.delivery = delivery_ratios()
        self.results = results_times()
        sast = [x for _, found in rep._parsed("sast", rep.promoter_buys) for x in found]
        self.promoters = rep.promoter_events(sast, self.sessions)
        etf_days = rs.load_days(ETF, cache=False)
        self.etf = {d.day: s for d in etf_days if (s := six.snap(d)) is not None}
        self.vix = _vix_minutes()

    def prev(self, day: date) -> date | None:
        return self.mk.prev(day)


def _vix_minutes() -> dict[date, Sequence[float]]:
    from eulerlab.intraday import index_futures_screen as fut

    return {d.day: d.close for d in fut.load_index("INDIAVIX")}


# --- swing rules ---------------------------------------------------------------------


def _week_starts(sessions: Sequence[date]) -> list[tuple[date, date]]:
    """(first, last) session of each week."""
    weeks: dict[tuple[int, int], list[date]] = defaultdict(list)
    for d in sessions:
        weeks[d.isocalendar()[:2]].append(d)
    return [(min(v), max(v)) for _, v in sorted(weeks.items())]


def h0151(ctx: Context) -> list[Swing]:
    from eulerlab.intraday import option_iv_screen as iv

    found = []
    for first, last in _week_starts(ctx.window):
        p = ctx.prev(first)
        if p is None or p not in ctx.options:
            continue
        scored = []
        for symbol in ctx.mk.liquid.get(first, [])[:100]:
            chain, before = ctx.options[p].get(symbol), ctx.mk.snaps[symbol].get(p)
            if chain is None or before is None:
                continue
            spread = iv.day_signals(chain, before.last_close, p, None)["spread"]
            if spread is not None:
                scored.append((spread, symbol))
        scored.sort(reverse=True)
        hold = ctx.sessions.index(last) - ctx.sessions.index(first)
        for rank, (_, symbol) in enumerate(scored[:10]):
            if s := swing(ctx.mk.snaps[symbol], ctx.sessions, symbol, first, hold):
                found.append((first, float(rank), symbol, s))
    return cap_swings(found)


def _session_on_or_after(sessions: Sequence[date], day: date) -> int:
    return bisect.bisect_left(sessions, day)


def h0152(ctx: Context) -> list[Swing]:
    found = []
    allowed = set(ctx.window)
    for symbol, times in ctx.results.items():
        snaps = ctx.mk.snaps.get(symbol)
        if not snaps:
            continue
        last_used: datetime | None = None
        for when in times:
            if last_used is not None and (when - last_used).days < 30:
                continue
            last_used = when
            day = when.date()
            opened = when.time() < time(9, 15)
            i = _session_on_or_after(ctx.sessions, day)
            if i >= len(ctx.sessions) or i == 0:
                continue
            reaction = (
                i
                if (opened and ctx.sessions[i] == day)
                else (i if ctx.sessions[i] > day else i + 1)
            )
            entry = i - 1  # the last session before the disclosure date
            if reaction >= len(ctx.sessions) or ctx.sessions[entry] not in allowed:
                continue
            if symbol not in ctx.mk.liquid.get(ctx.sessions[entry], [])[:200]:
                continue
            hold = reaction - entry
            if s := swing(snaps, ctx.sessions, symbol, ctx.sessions[entry], hold):
                found.append((ctx.sessions[entry], 0.0, symbol, s))
    return cap_swings(found)


def h0153(ctx: Context) -> list[Swing]:
    found = []
    allowed = set(ctx.window)
    for symbol, days in ctx.promoters.items():
        snaps = ctx.mk.snaps.get(symbol)
        if not snaps:
            continue
        for day, share in days.items():
            if day in allowed and (s := swing(snaps, ctx.sessions, symbol, day, 20)):
                found.append((day, -share, symbol, s))
    return cap_swings(found)


def h0154(ctx: Context) -> list[Swing]:
    days = sorted(ctx.participants)
    etf_sessions = sorted(ctx.etf)
    out: list[Swing] = []
    for i in range(PCTL_DAYS, len(days)):
        day = days[i]
        history = [net_futures(ctx.participants[d]["Client"]) for d in days[i - PCTL_DAYS : i]]
        value = net_futures(ctx.participants[day]["Client"])
        if percentile_rank(history, value) >= 0.10:
            continue
        j = bisect.bisect_right(etf_sessions, day)
        if j >= len(etf_sessions):
            continue
        entry = etf_sessions[j]
        if entry not in set(ctx.window) or (out and out[-1].exit_day >= entry):
            continue
        if s := swing(ctx.etf, etf_sessions, ETF, entry, 5, notional=CAPITAL):
            out.append(s)
    return out


def h0155(ctx: Context) -> list[Swing]:
    found = []
    allowed = set(ctx.window)
    for day in ctx.window:
        p = ctx.prev(day)
        if p is None:
            continue
        for symbol in ctx.mk.liquid.get(day, [])[:200]:
            from eulerlab.intraday import quant_screen as qs

            r = qs._ret(ctx.mk, symbol, p)
            if r is None or r > -0.05:
                continue
            q = ctx.prev(p)
            if q is None:
                continue
            news = onex.had_news(
                ctx.news.get(symbol, ()), onex._at(q, onex.CLOSE), onex._at(p, onex.CLOSE)
            )
            if news or day not in allowed:
                continue
            if s := swing(ctx.mk.snaps[symbol], ctx.sessions, symbol, day, 10):
                found.append((day, r, symbol, s))
    return cap_swings(found)


# --- intraday rules ------------------------------------------------------------------


def _high_beta(ctx: Context, day: date, n: int = 5) -> list[str]:
    pool = [
        (-(b), s)
        for s in ctx.mk.liquid.get(day, [])[:100]
        if (b := ctx.mk.beta.get((s, day))) is not None and mft._today(ctx.mk, s, day) is not None
    ]
    return [s for _, s in sorted(pool)[:n]]


def _participant_side(
    ctx: Context, day: date, who: str, measure: Callable[[Mapping[str, int]], int]
) -> int:
    """+1 if yesterday's change is in the top tenth of 250 sessions, -1 bottom tenth, else 0."""
    days = sorted(d for d in ctx.participants if d < day)
    if len(days) < PCTL_DAYS + 2:
        return 0
    changes = [
        measure(ctx.participants[b][who]) - measure(ctx.participants[a][who])
        for a, b in zip(days[-PCTL_DAYS - 2 : -1], days[-PCTL_DAYS - 1 :], strict=True)
    ]
    rank = percentile_rank(changes[:-1], changes[-1])
    return 1 if rank >= 0.9 else -1 if rank <= 0.1 else 0


def _basket(ctx: Context, day: date, side: int, start: int = 5) -> Iterator[mft.Signal]:
    for symbol in _high_beta(ctx, day):
        if sig := mft.held(ctx.mk.snaps[symbol][day], day, symbol, side, start):
            yield sig


def h0156(ctx: Context, day: date) -> Iterator[mft.Signal]:
    side = _participant_side(ctx, day, "Client", net_futures)
    if side:
        yield from _basket(ctx, day, -side)


def h0157(ctx: Context, day: date) -> Iterator[mft.Signal]:
    side = _participant_side(ctx, day, "Pro", net_futures)
    if side:
        yield from _basket(ctx, day, side)


def h0158(ctx: Context, day: date) -> Iterator[mft.Signal]:
    vix, prev = ctx.vix.get(day), _official_vix(ctx).get(ctx.prev(day) or day)
    if vix is None or not prev or vix[15] < 1.05 * prev:
        return
    yield from _basket(ctx, day, 1, start=15)


_VIX: dict[date, float] = {}


def _official_vix(ctx: Context) -> dict[date, float]:
    if not _VIX:
        _VIX.update(mft._official_closes("India VIX"))
    return _VIX


def h0159(ctx: Context, day: date) -> Iterator[mft.Signal]:
    side = _participant_side(ctx, day, "FII", net_puts)
    if side:
        yield from _basket(ctx, day, -side)


def h0160(ctx: Context, day: date) -> Iterator[mft.Signal]:
    p = ctx.prev(day)
    if p is None:
        return
    from eulerlab.intraday import quant_screen as qs

    found = []
    for symbol in ctx.mk.liquid.get(day, [])[:100]:
        r, ratio = qs._ret(ctx.mk, symbol, p), ctx.delivery.get(symbol, {}).get(p)
        if r is not None and ratio is not None and r >= 0.03 and ratio <= 0.5:
            found.append((ratio, symbol, -1))
    yield from onex._cap(found, onex.Context(ctx.mk, {}, {}, frozenset()), day)


SWING_RULES: dict[str, tuple[str, Callable[[Context], list[Swing]]]] = {
    "H-0151": ("swing_call_put_iv_spread_week", h0151),
    "H-0152": ("swing_earnings_announcement_premium", h0152),
    "H-0153": ("swing_promoter_buy_20d", h0153),
    "H-0154": ("swing_retail_short_niftybees_5d", h0154),
    "H-0155": ("swing_no_news_loser_10d", h0155),
}
DAY_RULES: dict[str, tuple[str, Callable[[Context, date], Iterator[mft.Signal]]]] = {
    "H-0156": ("day_client_contrarian_high_beta", h0156),
    "H-0157": ("day_pro_follow_high_beta", h0157),
    "H-0158": ("day_vix_open_spike_buy_high_beta", h0158),
    "H-0159": ("day_fii_put_surge_contrarian", h0159),
    "H-0160": ("day_low_delivery_rally_fade", h0160),
}


# --- running -------------------------------------------------------------------------


def day_trades(ctx: Context, hypothesis: str, *, delay: int = 0) -> list[cs.Trade]:
    _, rule = DAY_RULES[hypothesis]
    signals = []
    for day in ctx.window:
        for sig in rule(ctx, day):
            if not delay:
                signals.append(sig)
                continue
            s = ctx.mk.snaps[sig.symbol][day]
            late = mft.held(s, day, sig.symbol, sig.direction, sig.decided, delay=delay)
            if late is not None:
                signals.append(late)
    out = []
    for sig in mft.book(signals):
        fill = five.Fill(
            sig.decided,
            sig.direction,
            sig.entry_minute,
            sig.entry,
            sig.exit_minute,
            sig.exit,
            sig.reason,
        )
        if trade := five._trade(sig.symbol, sig.day, fill, sig.direction, TRADE):
            out.append(trade)
    return out


def _summary(
    run_id: str, pieces: Sequence[Any], sessions: Sequence[date], extra: dict[str, Any]
) -> dict[str, Any]:
    net: dict[date, float] = defaultdict(float)
    twice: dict[date, float] = defaultdict(float)
    for p in pieces:
        net[p.day] += (p.gross - p.costs) / CAPITAL
        twice[p.day] += (p.gross - 2 * p.costs) / CAPITAL
    daily = [net.get(d, 0.0) for d in sessions]
    middle = len(daily) // 2
    years: dict[int, list[float]] = defaultdict(list)
    for d in sessions:
        years[d.year].append(net.get(d, 0.0))
    return {
        "id": run_id,
        "net": sc.daily_stats(daily),
        "halves": {
            "first": sc.daily_stats(daily[:middle]),
            "second": sc.daily_stats(daily[middle:]),
        },
        "net_at_2x_costs": sc.daily_stats([twice.get(d, 0.0) for d in sessions]),
        "net_by_year": {str(y): sc.daily_stats(v) for y, v in sorted(years.items())},
        **extra,
    }


def evaluate_swing(ctx: Context, hypothesis: str) -> dict[str, Any]:
    run_id, rule = SWING_RULES[hypothesis]
    positions = rule(ctx)
    pieces = [p for s in positions for p in s.pieces()]
    gross = [s.gross_total / s.notional * 1e4 for s in positions]
    net = [(s.gross_total - sum(s.costs_at())) / s.notional * 1e4 for s in positions]
    etf_excess = _excess_over_etf(ctx, positions)
    return {
        "hypothesis": hypothesis,
        **_summary(
            run_id,
            pieces,
            ctx.window,
            {
                "positions": len(positions),
                "per_position_bps": {
                    "gross_mean": round(statistics.fmean(gross), 2) if gross else None,
                    "net_mean": round(statistics.fmean(net), 2) if net else None,
                    "net_over_niftybees_mean": etf_excess,
                },
            },
        ),
    }


def _excess_over_etf(ctx: Context, positions: Sequence[Swing]) -> float | None:
    out = []
    for s in positions:
        a, b = ctx.etf.get(s.entry_day), ctx.etf.get(s.exit_day)
        if a is None or b is None:
            continue
        etf = (b.exit / a.entry - 1.0) * 1e4
        out.append((s.gross_total - sum(s.costs_at())) / s.notional * 1e4 - etf)
    return round(statistics.fmean(out), 2) if out else None


def evaluate_day(ctx: Context, hypothesis: str) -> dict[str, Any]:
    run_id, _ = DAY_RULES[hypothesis]
    trades = day_trades(ctx, hypothesis)
    gross = [t.gross / t.notional * 1e4 for t in trades if t.notional]
    net = [(t.gross - t.costs) / t.notional * 1e4 for t in trades if t.notional]
    return {
        "hypothesis": hypothesis,
        **_summary(
            run_id,
            trades,
            ctx.window,
            {
                "trades": len(trades),
                "per_trade_bps": {
                    "gross_mean": round(statistics.fmean(gross), 2) if gross else None,
                    "net_mean": round(statistics.fmean(net), 2) if net else None,
                },
            },
        ),
    }


_CTX: Context | None = None


def _context() -> Context:
    global _CTX
    if _CTX is None:
        _CTX = Context()
    return _CTX


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    ctx = _context()
    if hypothesis in SWING_RULES:
        pieces = [p for s in SWING_RULES[hypothesis][1](ctx) for p in s.pieces()]
        return IntradayRun(pieces, [], ctx.window, CAPITAL)
    return IntradayRun(
        day_trades(ctx, hypothesis),
        day_trades(ctx, hypothesis, delay=mft.LATE),
        ctx.window,
        CAPITAL,
    )


def passes(one: Mapping[str, Any]) -> bool:
    values = (
        one["halves"]["first"]["sharpe"],
        one["halves"]["second"]["sharpe"],
        one["net_at_2x_costs"]["sharpe"],
    )
    return all(v is not None and v > 0 for v in values)


def run(output: Path = OUT) -> dict[str, Any]:
    ctx = _context()
    runs = [evaluate_swing(ctx, h) for h in SWING_RULES] + [evaluate_day(ctx, h) for h in DAY_RULES]
    result = {"research": "172", "spent_trials": 0, "runs": runs}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="other-data-screen")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for one in run(args.output)["runs"]:
        per = one.get("per_position_bps") or one.get("per_trade_bps")
        count = one.get("positions", one.get("trades"))
        print(
            f"{one['hypothesis']} {one['id']}: {count}; {per}; net Sharpe {one['net']['sharpe']}; "
            f"halves {one['halves']['first']['sharpe']} / {one['halves']['second']['sharpe']}; "
            f"2x {one['net_at_2x_costs']['sharpe']}; {'PASS' if passes(one) else 'fail'}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
