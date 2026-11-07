"""Ten stock day trades at 1x (research 171, H-0141 to H-0150).

₹1 lakh a position with no leverage, at most ten open on ₹10 lakh of
capital: 12.24 bps a round trip. Same snapshots, fills, liquidity ranking and
window as `mft_screen` (research 168). Screen as research 170: a rule is
gated only if net positive in both halves and at twice the costs.

- **H-0141 / H-0142** a 2% gap with no news filing is faded; with one, followed (Chan 2003).
- **H-0143 / H-0144** yesterday's 4% move: no news faded, news followed.
- **H-0145** tug of war, three a side. **H-0146** tug of war where today's gap agrees.
- **H-0147** short on each ban day after the first.
- **H-0148** the ten highest-beta liquid stocks on the session before a holiday.
- **H-0149** Monday fade of the previous session's five biggest movers each way.
- **H-0150** a strong (weak) close on twice normal turnover, followed next day.

News = an NSE filing outside `ADMIN` (fixed before any run, research 171).
`make onex-screen` writes `data/derived/onex_screen.json`.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import mft_screen as mft
from eulerlab.intraday import quant_screen as qs
from eulerlab.intraday import screen_common as sc

OUT = Path("data/derived/onex_screen.json")
NEWS_CACHE = Path("data/derived/nse_news_times.json")
IST = ZoneInfo("Asia/Kolkata")
TRADE = 100_000.0
CAPITAL = 1_000_000.0
DECIDE = 5
CLOSE = time(15, 30)

ADMIN = frozenset(
    {
        "Loss of Share Certificates",
        "Loss of share certificate",
        "Issue of Duplicate Share Certificate",
        "Trading Window",
        "Closure of trading window",
        "Copy of Newspaper Publication",
        "Newspaper Advertisements",
        "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
        "Shareholders meeting",
        "Annual General Meeting",
        "Postal Ballot",
        "Book Closure",
        "Record Date",
        "Registrar & Share Transfer Agent Update",
        "Code of Conduct under SEBI(PIT) Reg., 2015",
        "ESOP/ESOS/ESPS",
        "ESOP/ESPS/SBEB Scheme",
        "Allotment of Securities",
        "Change in Company Secretary/Compliance Officer",
        "Annual Secretarial Compliance Report",
        "Monitoring Agency Report",
        "Analysts/Institutional Investor Meet/Con. Call Updates",
        "Schedule of Analysts/Institutional Investor Meet/Con. Call",
        "Transcript of Analysts/Institutional Investor Meet/Con. Call",
        "Recording of Analysts/Institutional Investor Meet/Con. Call",
    }
)
"""Filing categories that are not news (research 171)."""


# --- news ----------------------------------------------------------------------------


def news_times(rows: Sequence[Mapping[str, Any]], symbols: set[str]) -> dict[str, list[datetime]]:
    """{symbol: dissemination times of its news filings}, sorted."""
    out: dict[str, list[datetime]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if symbol not in symbols or str(row.get("desc") or "").strip() in ADMIN:
            continue
        try:
            # NSE writes Indian time without a zone.
            when = datetime.strptime(str(row.get("exchdisstime")), "%d-%b-%Y %H:%M:%S").replace(
                tzinfo=IST
            )
        except ValueError:
            continue
        out[symbol].append(when)
    return {s: sorted(v) for s, v in out.items()}


def load_news(symbols: set[str], path: Path = NEWS_CACHE) -> dict[str, list[datetime]]:
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {s: [datetime.fromisoformat(t) for t in v] for s, v in raw.items()}
    from eulerlab.ingest import landing_reader

    rows: list[dict[str, Any]] = []
    for name in sorted(landing_reader.available("nse_announcements", "*.json")):
        rows.extend(json.loads(landing_reader.read(name, cache=True)))
    found = news_times(rows, symbols)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({s: [t.isoformat() for t in v] for s, v in found.items()}))
    return found


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=IST)


def had_news(times: Sequence[datetime], start: datetime, end: datetime) -> bool:
    return any(start <= t < end for t in times)


# --- context -------------------------------------------------------------------------


class Context:
    """The research market plus what these rules add: news, bans, holidays."""

    def __init__(
        self,
        mk: mft.Market,
        news: Mapping[str, Sequence[datetime]],
        bans: Mapping[date, set[str]],
        holidays: frozenset[date],
    ) -> None:
        self.mk, self.news, self.bans, self.holidays = mk, news, bans, holidays

    def overnight_news(self, symbol: str, day: date) -> bool | None:
        p = self.mk.prev(day)
        if p is None:
            return None
        return had_news(self.news.get(symbol, ()), _at(p, CLOSE), _at(day, time(9, 15)))

    def day_news(self, symbol: str, day: date) -> bool | None:
        """Any news from the previous session's close to this session's close."""
        p = self.mk.prev(day)
        if p is None:
            return None
        return had_news(self.news.get(symbol, ()), _at(p, CLOSE), _at(day, CLOSE))


def _cap(
    found: list[tuple[float, str, int]], ctx: Context, day: date, n: int = 10
) -> Iterator[mft.Signal]:
    for _, symbol, side in sorted(found)[:n]:
        sig = mft.held(ctx.mk.snaps[symbol][day], day, symbol, side, DECIDE)
        if sig:
            yield sig


def _gap_rule(follow_news: bool) -> Callable[[Context, date], Iterator[mft.Signal]]:
    def rule(ctx: Context, day: date) -> Iterator[mft.Signal]:
        found = []
        for symbol in ctx.mk.liquid.get(day, [])[:200]:
            g, news = qs._gap(ctx.mk, symbol, day), ctx.overnight_news(symbol, day)
            if (
                g is None
                or news is None
                or abs(g) < 0.02
                or mft._today(ctx.mk, symbol, day) is None
            ):
                continue
            if news == follow_news:
                side = (1 if g > 0 else -1) * (1 if follow_news else -1)
                found.append((-abs(g), symbol, side))
        yield from _cap(found, ctx, day)

    return rule


def _yesterday_rule(follow_news: bool) -> Callable[[Context, date], Iterator[mft.Signal]]:
    def rule(ctx: Context, day: date) -> Iterator[mft.Signal]:
        p = ctx.mk.prev(day)
        if p is None:
            return
        found = []
        for symbol in ctx.mk.liquid.get(day, [])[:200]:
            r, news = qs._ret(ctx.mk, symbol, p), ctx.day_news(symbol, p)
            if (
                r is None
                or news is None
                or abs(r) < 0.04
                or mft._today(ctx.mk, symbol, day) is None
            ):
                continue
            if news == follow_news:
                side = (1 if r > 0 else -1) * (1 if follow_news else -1)
                found.append((-abs(r), symbol, side))
        yield from _cap(found, ctx, day)

    return rule


def h0145(ctx: Context, day: date) -> Iterator[mft.Signal]:
    scored = []
    for symbol in ctx.mk.liquid.get(day, [])[:100]:
        if mft._today(ctx.mk, symbol, day) is None:
            continue
        value = qs.s0132(ctx.mk, symbol, day)
        if value is not None:
            scored.append((value, symbol))
    if len(scored) < qs.MIN_NAMES:
        return
    scored.sort()
    for side, chosen in ((1, scored[:3]), (-1, scored[-3:])):
        for _, symbol in chosen:
            sig = mft.held(ctx.mk.snaps[symbol][day], day, symbol, side, DECIDE)
            if sig:
                yield sig


def h0146(ctx: Context, day: date) -> Iterator[mft.Signal]:
    scored = []
    for symbol in ctx.mk.liquid.get(day, [])[:100]:
        if mft._today(ctx.mk, symbol, day) is None:
            continue
        value, g = qs.s0132(ctx.mk, symbol, day), qs._gap(ctx.mk, symbol, day)
        if value is not None and g is not None:
            scored.append((value, symbol, g))
    if len(scored) < qs.MIN_NAMES:
        return
    scored.sort()
    decile = len(scored) // 10
    found = [(-v, s, -1) for v, s, g in scored[-decile:] if g >= 0.005]
    found += [(v, s, 1) for v, s, g in scored[:decile] if g <= -0.005]
    yield from _cap(found, ctx, day)


def h0147(ctx: Context, day: date) -> Iterator[mft.Signal]:
    p = ctx.mk.prev(day)
    if p is None or day not in ctx.bans or p not in ctx.bans:
        return
    found = [
        (0.0, s, -1)
        for s in sorted(ctx.bans[day] & ctx.bans[p])
        if mft._today(ctx.mk, s, day) is not None
    ]
    yield from _cap(found, ctx, day)


def _next_weekday(day: date) -> date:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def h0148(ctx: Context, day: date) -> Iterator[mft.Signal]:
    if _next_weekday(day) not in ctx.holidays:
        return
    found = [
        (-b, s, 1)
        for s in ctx.mk.liquid.get(day, [])[:100]
        if (b := ctx.mk.beta.get((s, day))) is not None and mft._today(ctx.mk, s, day)
    ]
    yield from _cap(found, ctx, day)


def h0149(ctx: Context, day: date) -> Iterator[mft.Signal]:
    p = ctx.mk.prev(day)
    if p is None or day.weekday() > p.weekday():
        return  # not the first session of a week
    scored = [
        (r, s)
        for s in ctx.mk.liquid.get(day, [])[:100]
        if (r := qs._ret(ctx.mk, s, p)) is not None and mft._today(ctx.mk, s, day)
    ]
    yield from qs._long_short(ctx.mk, day, scored, True, None, 0)


def h0150(ctx: Context, day: date) -> Iterator[mft.Signal]:
    p = ctx.mk.prev(day)
    if p is None:
        return
    found = []
    for symbol in ctx.mk.liquid.get(day, [])[:100]:
        y, r, ratio = (
            ctx.mk.snaps[symbol].get(p),
            qs._ret(ctx.mk, symbol, p),
            qs.s0134(ctx.mk, symbol, day),
        )
        if y is None or r is None or ratio is None or ratio < 2.0 or abs(r) < 0.02:
            continue
        if mft._today(ctx.mk, symbol, day) is None:
            continue
        high, low = max(y.closes), min(y.closes)
        if high <= low:
            continue
        place = (y.last_close - low) / (high - low)
        if r > 0 and place >= 0.95:
            found.append((-ratio, symbol, 1))
        elif r < 0 and place <= 0.05:
            found.append((-ratio, symbol, -1))
    yield from _cap(found, ctx, day)


RULES: dict[str, tuple[str, Callable[[Context, date], Iterator[mft.Signal]]]] = {
    "H-0141": ("onex_no_news_gap_fade", _gap_rule(False)),
    "H-0142": ("onex_news_gap_follow", _gap_rule(True)),
    "H-0143": ("onex_no_news_move_fade_next_day", _yesterday_rule(False)),
    "H-0144": ("onex_news_move_follow_next_day", _yesterday_rule(True)),
    "H-0145": ("onex_tug_of_war_three", h0145),
    "H-0146": ("onex_tug_of_war_gap_agrees", h0146),
    "H-0147": ("onex_ban_continuation_short", h0147),
    "H-0148": ("onex_pre_holiday_high_beta", h0148),
    "H-0149": ("onex_monday_fade", h0149),
    "H-0150": ("onex_strong_close_follow", h0150),
}


# --- running -------------------------------------------------------------------------


def context() -> Context:
    from eulerlab.intraday import cash_events_screen as events
    from eulerlab.intraday import nse_reports_screen as rep

    mk = mft.market()
    window = sorted({d for days in mk.snaps.values() for d in days})
    bans = dict(rep._parsed("fo_ban", rep.ban_list))
    # ASSUMPTION A-110: a weekday with no session in the archive was a holiday.
    holidays = frozenset(_next_weekday(d) for d in events.pre_holiday_days(window))
    return Context(mk, load_news(set(mk.snaps)), bans, holidays)


def trades_for(ctx: Context, hypothesis: str, *, delay: int = 0) -> list[cs.Trade]:
    _, rule = RULES[hypothesis]
    signals = []
    for day in ctx.mk.sessions:
        for sig in rule(ctx, day):
            if delay:  # every rule here holds to 15:10
                s = ctx.mk.snaps[sig.symbol][day]
                late = mft.held(s, day, sig.symbol, sig.direction, sig.decided, delay=delay)
                if late:
                    signals.append(late)
            else:
                signals.append(sig)
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
        trade = five._trade(sig.symbol, sig.day, fill, sig.direction, TRADE)
        if trade:
            out.append(trade)
    return out


def evaluate(ctx: Context, hypothesis: str) -> dict[str, Any]:
    run_id, _ = RULES[hypothesis]
    trades = trades_for(ctx, hypothesis)
    sessions = ctx.mk.sessions
    run = cs.report(run_id, trades, sessions, params={"notional": TRADE}, capital=CAPITAL)
    daily = [r for _, r in run["daily"]]
    middle = len(daily) // 2
    run["halves"] = {
        "first": sc.daily_stats(daily[:middle]),
        "second": sc.daily_stats(daily[middle:]),
    }
    by_day: dict[date, float] = defaultdict(float)
    for t in trades:
        by_day[t.day] += (t.gross - 2 * t.costs) / CAPITAL
    run["net_at_2x_costs"] = sc.daily_stats([by_day.get(d, 0.0) for d in sessions])
    run["hypothesis"] = hypothesis
    run["trades_a_day"] = round(len(trades) / len(sessions), 2) if sessions else 0
    run["costs_bps_a_trade"] = (
        round(sum(t.costs for t in trades) / sum(t.notional for t in trades) * 1e4, 2)
        if trades
        else None
    )
    run.pop("trade_log", None)
    return run


_CTX: Context | None = None


def _context() -> Context:
    global _CTX
    if _CTX is None:
        _CTX = context()
    return _CTX


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    ctx = _context()
    return IntradayRun(
        trades_for(ctx, hypothesis),
        trades_for(ctx, hypothesis, delay=mft.LATE),
        ctx.mk.sessions,
        CAPITAL,
    )


def run(output: Path = OUT) -> dict[str, Any]:
    ctx = _context()
    result = {"research": "171", "spent_trials": 0, "runs": [evaluate(ctx, h) for h in RULES]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="onex-screen")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for one in run(args.output)["runs"]:
        pt = one["per_trade_bps"]
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades ({one['trades_a_day']}/day); "
            f"{pt['gross_mean']} gross, {pt['net_mean']} net bps (cost {one['costs_bps_a_trade']}); "
            f"net Sharpe {one['net']['sharpe']}; halves {one['halves']['first']['sharpe']} / "
            f"{one['halves']['second']['sharpe']}; 2x {one['net_at_2x_costs']['sharpe']}; "
            f"{'PASS' if qs.passes_screen(one) else 'fail'}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
