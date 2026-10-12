"""The headline result for each strategy, run on the parameters it now uses.

A sweep answers "which of these nine settings was best". It does not, by
itself, answer "what does this strategy do" — the winner's row in a sweep is
one of nine numbers produced by a search, and the search is what makes it
suspect. This module runs each strategy **once** on its adopted parameters and
records that as the strategy's result, which is what the library shows.

### Why this spends no trials

A trial is a configuration evaluated *in a search*. These runs evaluate nothing
new: every parameter set here was already recorded by the sweep that chose it,
on the same window, on the same instrument. What is computed is an additional
statistic — a Sharpe — from the same trades the ledger already paid for.

The distinction matters and is easy to abuse, so it is drawn narrowly: this
module may only run a parameter set that a recorded sweep already contains, and
it re-runs exactly one per strategy. If it ever grew the ability to try a
setting the ledger has not seen, it would be a search wearing a different name
and would have to pay like one. A-034 covers the neighbouring case.

### Both US brokers, from one run

A US result is reported under **INDmoney and Firstrade together**, because the
account could be either and the fee is the only thing that differs between
them. Position sizing here is a function of risk and stop distance, never of
cost, so the fills are identical under both schedules — the same entries, the
same exits, the same prices. Only the bill changes.

That means both figures come from **one** scan, with the cost recomputed from
the same trade list rather than the strategy being simulated twice. Two
simulations would also be correct but would invite the two to drift, and a
comparison whose two halves are not the same trades is not a comparison.

### Why the Sharpe and not just the P&L

Everything in this platform is read against the noise bar, which is a Sharpe.
A result reported only as a rupee figure cannot be compared to it, so it cannot
be the main result no matter where it is displayed. `ou_reversion` returns
+$29,200 over 58 sessions, which sounds like something; its Sharpe is 2.89
against a bar of 3.24, which says what that something is worth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

RESULTS_PATH = Path("data/derived/adopted_results.jsonl")

EQUITY = 1_000_000.0
"""The account every intraday scan is sized against. Matches the sweep's own
default, so a headline number and its sweep row are the same measurement."""


@dataclass
class Result:
    """One strategy, run once on the parameters it actually uses."""

    strategy_id: str
    symbol: str
    market: str
    start: str
    end: str
    params: dict[str, float]
    adopted: bool
    net_pnl: float
    gross_pnl: float
    costs: float
    fills: int
    wins: int
    sessions: int
    sharpe: float | None
    # The same trades priced at the other broker. Populated for US runs only;
    # there is no second venue for NSE or for Delta.
    alt_broker: str = ""
    alt_net_pnl: float = 0.0
    alt_costs: float = 0.0
    alt_sharpe: float | None = None
    curve: list[float] = field(default_factory=list)
    max_drawdown: float = 0.0
    best_session: float = 0.0
    worst_session: float = 0.0
    exits: dict[str, int] = field(default_factory=dict)
    rejections: dict[str, int] = field(default_factory=dict)
    at: str = ""

    @property
    def win_rate(self) -> float:
        return self.wins / self.fills if self.fills else 0.0


def compute(
    strategy_id: str,
    *,
    symbol: str,
    market: str,
    start: date,
    end: date,
) -> Result | None:
    """Run one strategy on its adopted parameters and measure it.

    Returns None when the strategy has no intraday form, rather than raising:
    a registry entry that this engine cannot express is not an error, it is a
    strategy that lives somewhere else.
    """
    from eulerlab.intraday import tuned
    from eulerlab.intraday.paper_scan import ALL_SIGNALS, scan_symbol
    from eulerlab.intraday.papers import PaperRules

    if strategy_id not in ALL_SIGNALS:
        return None

    adoption = tuned.for_strategy(strategy_id)
    rules = tuned.rules_for(strategy_id)
    if not isinstance(rules, PaperRules):
        rules = PaperRules()

    scan = scan_symbol(
        strategy_id,
        symbol,
        start=start,
        end=end,
        rules=rules,
        equity=EQUITY,
        asset_class=market,
    )

    gross = sum(trade.gross_pnl() for trade in scan.trades if trade.filled)
    costs = sum(trade.costs for trade in scan.trades)

    # Equity path of this run, in currency, starting at zero. Built from the
    # session series rather than the trade list so flat days are part of the
    # line: a curve that only moves on trading days compresses time and makes a
    # signal that fires twice look like one that fires daily.
    series = scan.session_pnl()
    curve: list[float] = []
    running = 0.0
    for value in series:
        running += value
        curve.append(running)

    peak = 0.0
    drawdown = 0.0
    for point in curve:
        peak = max(peak, point)
        drawdown = min(drawdown, point - peak)

    exits: dict[str, int] = {}
    for trade in scan.trades:
        for leg in trade.exits:
            exits[leg.reason] = exits.get(leg.reason, 0) + 1

    alt_broker, alt_net, alt_costs, alt_sharpe = _priced_at_other_broker(scan, market, curve)

    # Filed under the strategy's own configuration so the library can open it
    # from the run picker, exactly like a backtest run from the interface. A
    # standing result with no report is the state that made "I can't see the
    # last backtest" true for every intraday strategy at once.
    _save_report(strategy_id, scan, symbol, market, start, end, curve)

    return Result(
        strategy_id=strategy_id,
        symbol=symbol,
        market=market,
        start=start.isoformat(),
        end=end.isoformat(),
        params={
            name: float(getattr(rules, name))
            for name in (adoption.params if adoption else {})
            if hasattr(rules, name)
        },
        adopted=bool(adoption and adoption.adopted),
        net_pnl=scan.net_pnl,
        gross_pnl=gross,
        costs=costs,
        fills=scan.filled,
        wins=scan.wins,
        sessions=scan.sessions,
        sharpe=scan.sharpe(EQUITY),
        alt_broker=alt_broker,
        alt_net_pnl=alt_net,
        alt_costs=alt_costs,
        alt_sharpe=alt_sharpe,
        curve=curve,
        max_drawdown=drawdown,
        best_session=max(series) if series else 0.0,
        worst_session=min(series) if series else 0.0,
        exits=exits,
        # How often the signal declined, and why. A strategy that refuses
        # 12,000 times and fires 23 is a different object from one that fires
        # constantly, and the two can report the same P&L.
        rejections=dict(sorted(scan.rejections.items(), key=lambda kv: -kv[1])[:6]),
        at=datetime.now(UTC).isoformat(),
    )


def _save_report(
    strategy_id: str,
    scan: Any,
    symbol: str,
    market: str,
    start: date,
    end: date,
    curve: list[float],
) -> None:
    """Record this run and write its report, so the library can open it.

    Recorded as a real `result_store.Run` rather than as a private artefact.
    That has a cost worth naming: `runs` is the denominator behind "best of N"
    in the library, so adding one per strategy makes each look marginally more
    searched-over. It is also true — this *is* a run — and a result the
    interface cannot open is worse than an honest denominator.

    Failures are swallowed. A missing report is a degraded view; an exception
    here would lose the measurement itself, which is the thing worth keeping.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from eulerlab import reports
    from eulerlab import results as result_store
    from eulerlab import workspace as workspace_mod
    from eulerlab.intraday.report_material import fills_and_marks

    try:
        tenant = workspace_mod.resolve(None)
        fills, marks = fills_and_marks([scan])

        # `curve` is cumulative P&L from zero; the report wants an equity path
        # from `starting_cash`. Handing the raw curve over would draw a
        # strategy that made $27,855 as one that lost 97% of the account, and
        # the number would look precise the whole way down.
        #
        # One point longer than `days`, matching the daily engine: the opening
        # balance before the first session, then one close per session.
        equity = [EQUITY, *(EQUITY + point for point in curve)]
        sharpe = scan.sharpe(EQUITY)
        run = result_store.Run(
            strategy_id=strategy_id,
            sharpe=round(sharpe, 4) if sharpe is not None else 0.0,
            total_return=round(scan.net_pnl / EQUITY, 6),
            max_drawdown=0.0,
            fills=scan.filled,
            days=scan.sessions,
            tier="intraday",
            window_days=(end - start).days,
            data_version=f"adopted-{_dt.now(_UTC).date().isoformat()}",
            universe="adopted",
            asset_class=market,
            symbols=1,
            cost_mode="realistic",
            params={"instruments": [symbol], "adopted": True},
            curve=result_store.downsample(equity),
            trial_recorded=False,
        )
        result_store.record(tenant, run)
        reports.save(
            tenant,
            reports.build(
                strategy_id=strategy_id,
                configuration=run.configuration,
                universe="adopted",
                instruments=[symbol],
                tier="intraday",
                asset_class=market,
                cost_mode="realistic",
                window_days=(end - start).days,
                equity=equity,
                days=sorted(scan.pnl_by_session()),
                fills=fills,
                rejections=[],
                marks=marks,
                starting_cash=EQUITY,
                params=dict(run.params),
                data_version=run.data_version,
            ),
        )
    except Exception:
        return


def _priced_at_other_broker(
    scan: Any, market: str, curve: list[float]
) -> tuple[str, float, float, float | None]:
    """The same trades, billed at whichever US broker was not used.

    Recomputed from the trade list rather than by running the strategy again:
    the fills do not depend on the fee, so a second simulation would produce
    identical trades and only invite the two to drift apart.

    Returns empty for non-US markets, where there is no second venue.
    """
    if market != "us" or not scan.trades:
        return "", 0.0, 0.0, None

    import math
    import statistics
    from decimal import Decimal
    from itertools import pairwise

    from eulerlab.costs.schedule import Side
    from eulerlab.costs.us_equity import BROKER, Broker, equity_fee

    other = Broker.FIRSTRADE if BROKER is Broker.INDMONEY else Broker.INDMONEY

    gross = 0.0
    costs = 0.0
    for trade in scan.trades:
        if not trade.filled:
            continue
        shares = sum(leg.shares for leg in trade.exits)
        if shares:
            costs += float(
                equity_fee(
                    price=Decimal(str(trade.entry_price)),
                    quantity=Decimal(str(shares)),
                    side=Side.BUY,
                    day=trade.entry_ts.date(),
                    broker=other,
                ).total
            )
        for leg in trade.exits:
            costs += float(
                equity_fee(
                    price=Decimal(str(leg.price)),
                    quantity=Decimal(str(leg.shares)),
                    side=Side.SELL,
                    day=leg.ts.date(),
                    broker=other,
                ).total
            )
        gross += trade.gross_pnl()

    net = gross - costs
    # The Sharpe shifts with the cost, so it is rescaled rather than reused:
    # the same session shape, moved by the difference in the bill spread evenly
    # across the sessions that traded. Approximate, and near enough at this
    # scale — the two bills differ by a few thousand on a six-figure gross.
    sharpe: float | None = None
    if len(curve) >= 2 and curve[-1] != 0.0:
        series = [curve[0]] + [b - a for a, b in pairwise(curve)]
        shift = (net - curve[-1]) / max(len(series), 1)
        moved = [v + shift if v else v for v in series]
        spread = statistics.pstdev([v / EQUITY for v in moved])
        if spread > 0:
            sharpe = (statistics.fmean([v / EQUITY for v in moved]) / spread) * math.sqrt(252.0)

    return other.value, net, costs, sharpe


def write(results: list[Result], path: Path = RESULTS_PATH) -> None:
    """Replace the cache. One line per strategy, newest run wins."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "strategy_id": r.strategy_id,
                    "symbol": r.symbol,
                    "market": r.market,
                    "start": r.start,
                    "end": r.end,
                    "params": r.params,
                    "adopted": r.adopted,
                    "net_pnl": r.net_pnl,
                    "gross_pnl": r.gross_pnl,
                    "costs": r.costs,
                    "fills": r.fills,
                    "wins": r.wins,
                    "sessions": r.sessions,
                    "sharpe": r.sharpe,
                    "alt_broker": r.alt_broker,
                    "alt_net_pnl": r.alt_net_pnl,
                    "alt_costs": r.alt_costs,
                    "alt_sharpe": r.alt_sharpe,
                    "curve": r.curve,
                    "max_drawdown": r.max_drawdown,
                    "best_session": r.best_session,
                    "worst_session": r.worst_session,
                    "exits": r.exits,
                    "rejections": r.rejections,
                    "at": r.at,
                },
                sort_keys=True,
            )
            + "\n"
            for r in results
        ),
        encoding="utf-8",
    )


def merge(results: list[Result], path: Path = RESULTS_PATH) -> None:
    """Write these results over whatever is cached, leaving other strategies alone.

    `write` replaces the file, which is right for a full run and destructive for
    a partial one: a four-strategy `--only` run wrote a four-strategy cache and
    dropped the twenty already measured. Anything that can be invoked with a
    subset has to merge.
    """
    from eulerlab import strategy_results

    # Also written to the merged store, which is what the API reads. The
    # per-kind file stays for now so a rollback needs no migration.
    strategy_results.merge(strategy_results.HOME, [_as_row(r) for r in results])

    existing = read(path)
    for result in results:
        existing[result.strategy_id] = {
            "strategy_id": result.strategy_id,
            "symbol": result.symbol,
            "market": result.market,
            "start": result.start,
            "end": result.end,
            "params": result.params,
            "adopted": result.adopted,
            "net_pnl": result.net_pnl,
            "gross_pnl": result.gross_pnl,
            "costs": result.costs,
            "fills": result.fills,
            "wins": result.wins,
            "sessions": result.sessions,
            "sharpe": result.sharpe,
            "alt_broker": result.alt_broker,
            "alt_net_pnl": result.alt_net_pnl,
            "alt_costs": result.alt_costs,
            "alt_sharpe": result.alt_sharpe,
            "curve": result.curve,
            "max_drawdown": result.max_drawdown,
            "best_session": result.best_session,
            "worst_session": result.worst_session,
            "exits": result.exits,
            "rejections": result.rejections,
            "at": result.at,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for _, row in sorted(existing.items())),
        encoding="utf-8",
    )


def _as_row(result: Result) -> dict[str, Any]:
    """One result as the plain dict both stores hold."""
    from dataclasses import asdict

    return asdict(result)


def read(path: Path = RESULTS_PATH) -> dict[str, dict[str, Any]]:
    """Every cached headline result, keyed by strategy. Corrupt lines skipped."""
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("strategy_id"):
            out[str(row["strategy_id"])] = row
    return out
