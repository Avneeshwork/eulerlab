"""Running an intraday signal for the interface, and shaping the result.

Lifted out of `api/server` with the panel layer. Nearly two hundred lines of
engine work — choosing the symbol universe, scanning, turning bracket legs into
report rows — sitting in the module that also parses HTTP requests.

The seam is worth naming: **nothing here knows about HTTP.** It takes a request
object for its fields and returns a plain dict, which is why it could move at
all, and why leaving it in the transport layer was arbitrary rather than
convenient.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from eulerlab import results as result_store
from eulerlab.api.panels import cost_mode_for
from eulerlab.api.requests import (
    ALL_INSTRUMENTS,
    IST,
    BatchRunRequest,
    universe_label,
    window_of,
)
from eulerlab.strategies import AssetClass, catalog
from eulerlab.validation.statistics import sharpe_stats


def _drawdown(equity: list[float]) -> float:
    """Worst peak-to-trough fall, as a fraction."""
    peak, worst = equity[0] if equity else 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


if TYPE_CHECKING:
    from collections.abc import Sequence

INTRADAY_SYMBOL_CAP = 12
"""How many symbols an intraday run scans.

Minute bars are ~370 per symbol per session, so a six-month scan of one symbol
reads roughly 45,000 candles. The daily engine reads a prebuilt panel; this
fetches and replays. Twelve symbols keeps a run inside a couple of minutes,
and the cap is stated in the result rather than hidden, because a signal that
fired twice across twelve names is a different claim from one that fired twice
across four hundred.
"""

INTRADAY_SESSIONS_PER_YEAR = 250


TWEEZER = "tweezer_bottom"
"""The one intraday strategy that is not a paper signal: it runs through the
Tweezer scanner (`intraday/scan.py`) rather than `paper_scan`."""

TWEEZER_SYMBOL_CAP = 50
"""Tweezer reads 15-minute candles, a fifteenth of the minute bars a paper
signal replays, and the operator's report is a Nifty 50 result. Twelve names
would answer a different question from the one the report asks."""


def _intraday_symbols(request: BatchRunRequest, cap: int = INTRADAY_SYMBOL_CAP) -> list[str]:
    """Which symbols an intraday scan covers.

    Hand-picked instruments win, then the named universe, then whatever has
    minute bars. Always intersected with what actually has minute data, because
    a symbol with daily bars and no minute bars is not a smaller sample - it is
    an absent one.
    """
    # The symbol universe follows the asset class, because a crypto signal on
    # RELIANCE is not a smaller sample, it is a different question.
    if request.asset_class == AssetClass.CRYPTO.value:
        from eulerlab.intraday import crypto_store

        try:
            available = set(crypto_store.symbols())
        except Exception:
            available = set()
    elif request.asset_class == AssetClass.US.value:
        # Without this the US class fell through to the NSE store, matched
        # nothing, and every intraday US backtest failed with "no symbols with
        # minute bars for that selection" — which reads like missing data
        # rather than a missing branch.
        from eulerlab.intraday import us_store

        try:
            available = set(us_store.symbols())
        except Exception:
            available = set()
    else:
        from eulerlab.intraday import store

        try:
            available = set(store.available_symbols())
        except Exception:
            available = set()

    if request.instruments:
        wanted = [s.strip().upper() for s in request.instruments if s.strip()]
    elif request.asset_class != AssetClass.EQUITY.value:
        # Named batches are equity liquidity slices and mean nothing to another
        # class, so the whole landed universe is the universe.
        wanted = sorted(available)
    elif request.universe != ALL_INSTRUMENTS:
        wanted = list(catalog.universe(request.universe))
    else:
        wanted = sorted(available)

    kept = [s for s in wanted if not available or s in available]
    return kept[:cap]


def _run_intraday(strategy_id: str, request: BatchRunRequest) -> dict[str, Any]:
    """Scan one paper signal across minute bars and shape the result like a
    backtest.

    The Sharpe here is computed over **per-session** returns, not per-day
    returns of a continuously held portfolio. An intraday signal is flat
    overnight and flat on any session it does not fire, so a session it sat out
    contributes a zero - which is a real zero, not a missing observation. That
    makes this comparable to a daily Sharpe in construction but not in meaning,
    and the tier is recorded as `intraday` so the two are never silently
    ranked against each other.
    """

    from eulerlab.intraday import paper_scan

    cap = TWEEZER_SYMBOL_CAP if strategy_id == TWEEZER else INTRADAY_SYMBOL_CAP
    symbols = _intraday_symbols(request, cap)
    if not symbols:
        msg = "no symbols with minute bars for that selection"
        raise RuntimeError(msg)

    # Timezone-explicit: `date.today()` means whatever the running machine's
    # locale says, and an intraday window that silently shifts by a day is the
    # kind of bug that never surfaces as an error.
    # An explicit window when one was given, otherwise the last `days` days.
    # Without this every question ends today, so "how did this behave in 2022"
    # could not be asked at all.
    start, end = window_of(request)
    if start is None or end is None:
        end = datetime.now(UTC).astimezone(IST).date()
        start = end - timedelta(days=request.days)
    # Sized against the account the run is actually for.
    #
    # This omitted `equity`, so the scan sized every position against the
    # default one million while `total_return` divided by whatever the operator
    # asked for. A ₹5 lakh run reported **twice** the return it earned: the same
    # trades, in the numerator, over half the capital in the denominator.
    #
    # Position sizing here is a fraction of equity, so halving the account
    # should halve the P&L and leave the percentage alone. That it doubled is
    # exactly the tell.
    scans: Sequence[Any]
    if strategy_id == TWEEZER:
        # The operator's rules, on 15-minute candles (the report's own sizes are
        # 15, 30 and 60; `make tweezer-report` measures all three). NSE only:
        # the pattern's thresholds and the 15:00 cutoff are Indian-session facts.
        if request.asset_class != AssetClass.EQUITY.value:
            msg = "Tweezer Bottom is specified for NSE equities only"
            raise RuntimeError(msg)
        from eulerlab.intraday import scan as tweezer_scan

        scans = tweezer_scan.scan_many(symbols, start=start, end=end, equity=request.starting_cash)
        scans = [s for s in scans if s.days]
    else:
        scans = paper_scan.scan_many(
            strategy_id,
            symbols,
            start=start,
            end=end,
            equity=request.starting_cash,
            asset_class=request.asset_class,
        )
    if not scans:
        msg = f"no minute bars readable for any of {len(symbols)} symbols"
        raise RuntimeError(msg)

    # Per-session profit and loss, summed across symbols.
    by_session: dict[date, float] = {}
    sessions_seen: set[date] = set()
    fills = 0
    for scan in scans:
        for trade in scan.trades:
            if not trade.filled or trade.entry_ts is None:
                continue
            fills += 1
            day = trade.entry_ts.date()
            by_session[day] = by_session.get(day, 0.0) + trade.net_pnl()
    for scan in scans:
        for trade in scan.trades:
            if trade.entry_ts is not None:
                sessions_seen.add(trade.entry_ts.date())

    if fills == 0:
        msg = (
            f"no trade filled across {len(symbols)} symbols in {request.days} days. "
            f"The signal either never fired or never filled - check the rejection "
            f"reasons rather than reading this as a zero result."
        )
        raise RuntimeError(msg)

    cash_start = request.starting_cash
    # Every session the scan covered, not only the ones that traded.
    #
    # This walked `by_session`, which holds trading days alone — so a signal
    # firing on 24 of 63 sessions produced a 24-point equity curve with no flat
    # days in it. Three things were wrong at once: the report said "invested
    # 100% of the time, 0 flat days" of a strategy flat two thirds of it, the
    # volatility was measured over only the days it acted, and the Sharpe came
    # out **5.37 against the 3.69** the same run scores through
    # `SignalScan.sharpe`, which pads.
    #
    # That padding is the correct treatment and its docstring says why: a
    # session sat out is a real zero, not a missing observation, and dropping
    # it reports a daily trader's volatility for an occasional one — inflating
    # the ratio by roughly the square root of how rarely it fires.
    all_sessions = sorted({day for scan in scans for day in scan.session_days()})
    cash = cash_start
    equity = [cash]
    for day in all_sessions or sorted(by_session):
        cash += by_session.get(day, 0.0)
        equity.append(cash)

    returns = [b / a - 1.0 for a, b in pairwise(equity) if a > 0]
    stats = sharpe_stats(returns, periods_per_year=INTRADAY_SESSIONS_PER_YEAR)
    outcome: dict[str, Any] = {
        "sharpe": round(stats.sharpe, 4),
        "total_return": round(equity[-1] / cash_start - 1.0, 6),
        "max_drawdown": round(_drawdown(equity), 6),
        "fills": fills,
        "costs": round(sum(t.costs for s in scans for t in s.trades), 2),
        "days": len(equity) - 1,
        "universe": universe_label(request),
        "universe_size": len(symbols),
        "symbols": len({s.symbol for s in scans if s.trades}),
        "asset_class": request.asset_class,
        "cost_mode": cost_mode_for(request.asset_class),
        "curve": result_store.downsample(equity),
        "sessions_scanned": sum(s.sessions for s in scans),
        "symbol_cap": cap,
    }
    # Carried out rather than saved here, under a private key. A report is
    # filed under the run's `configuration` hash, and that hash is only known
    # where the `Run` is built — which is the batch recorder, not this
    # function. Building a second `Run` here to derive it produced a different
    # hash (this function has `tier="A"` from the request; the recorder writes
    # `tier="intraday"` from the payload), so the report landed under a
    # configuration nothing would ever look up.
    outcome["_report"] = _intraday_report_material(
        # The same session list the equity curve walks, so the report's day
        # count and its curve cannot disagree about how long the run was.
        strategy_id,
        request,
        scans,
        equity,
        all_sessions or sorted(by_session),
    )
    return outcome


def _benchmark_for(scans: Sequence[Any], request: BatchRunRequest) -> dict[str, Any] | None:
    """Buy-and-hold of the traded instrument, over the sessions it traded.

    Single-instrument only. A universe run would need an equal-weight basket to
    be comparable, and computing one from the fetched bars is a different and
    larger claim than "holding this one thing"; returning None is honest where
    that is not available, and a missing benchmark reads as missing rather than
    as zero.
    """
    from eulerlab import benchmark
    from eulerlab.intraday.paper_scan import candles_for

    traded = {scan.symbol for scan in scans if scan.trades}
    if len(traded) != 1:
        return None

    symbol = next(iter(traded))
    scan = next(s for s in scans if s.symbol == symbol)
    sessions = set(scan.pnl_by_session())
    if not sessions:
        return None

    end = datetime.now(UTC).astimezone(IST).date()
    start = end - timedelta(days=request.days)
    held = benchmark.hold(
        candles_for(symbol, start, end, asset_class=request.asset_class),
        symbol=symbol,
        asset_class=request.asset_class,
        starting_cash=1_000_000.0,
        traded_days=sessions,
    )
    if held is None:
        return None

    return {
        "symbol": held.symbol,
        "net_pnl": held.net_pnl,
        "total_return": held.total_return,
        "sharpe": held.sharpe,
        "max_drawdown": held.max_drawdown,
        "costs": held.costs,
    }


def _intraday_report_material(
    strategy_id: str,
    request: BatchRunRequest,
    scans: Sequence[Any],
    equity: list[float],
    days: list[date],
) -> dict[str, Any]:
    """Everything `reports.build` needs except the configuration hash.

    The fill extraction lives in `intraday/report_material` because
    `adopted_run` writes reports too, and two code paths producing the same
    report differently is two reports that cannot be compared.
    """
    from eulerlab.intraday.report_material import fills_and_marks

    fills, marks = fills_and_marks(list(scans))
    # The window of data the scan *saw*, which is not the window it traded.
    #
    # Two runs asking for 90 and 180 days both traded 2026-05-29..2026-08-20 and
    # both filled 24 times, and returned different P&L — because the longer
    # request fetched three more sessions of leading history, which changes ATR
    # warmup and therefore where the early stops sat. Reporting only the traded
    # window made two genuinely different runs look identical and the date range
    # look broken.
    seen = sorted({candle_day for scan in scans for candle_day in scan.session_days()})

    # What holding the instrument would have done over the same sessions.
    # Without it a return figure is a number rather than a result: +2.6% on QQQ
    # means one thing if QQQ rose 8% and the opposite if it fell 3%.
    bench = _benchmark_for(scans, request)
    return {
        "strategy_id": strategy_id,
        "universe": universe_label(request),
        "benchmark": bench,
        "data_window": [seen[0].isoformat(), seen[-1].isoformat()] if seen else [],
        "sessions_seen": len(seen),
        "requested_days": request.days,
        "instruments": sorted({s.symbol for s in scans}),
        "tier": request.tier,
        "asset_class": request.asset_class,
        "cost_mode": cost_mode_for(request.asset_class),
        "window_days": request.days,
        "equity": equity,
        "days": days,
        "fills": fills,
        # The intraday scanner records refusals by reason and count, not by
        # symbol and day, so the report's per-order rejection list has nothing
        # to show. Passed empty rather than fabricated.
        "rejections": [],
        "marks": marks,
        "starting_cash": request.starting_cash,
    }
