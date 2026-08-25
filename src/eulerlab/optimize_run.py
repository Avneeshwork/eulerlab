"""`make optimize` — sweep every strategy, on the market its paper tested.

Runs one strategy at a time and reports, for each, the best candidate **beside
the median**. The gap between them is the finding: the maximum of N draws from
noise rises with N, so a best far above its median has found the right tail of
a sample rather than an edge.

Each signal is swept on its `recommended_class` — the market its source paper
tested — because a signal published on US equity futures and swept on NSE
minute bars is being asked a different question than the one it answers.

The trial count is printed before and after. Every configuration evaluated is
permanent and raises the bar for every result this platform will ever produce,
so the cost is stated rather than buried.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Sequence

from eulerlab import optimize, optimize_store
from eulerlab.features import trials

SPACES: dict[str, dict[str, list[float]]] = {
    # Deliberately small. A three-point sweep of two parameters is nine trials
    # per strategy; a ten-point sweep of four would be ten thousand across the
    # library, and the deflated-Sharpe denominator does not forget.
    # The two knobs every bracket signal shares: where the stop sits and how
    # far the target reaches. Field names checked against `PaperRules` rather
    # than guessed — the first version swept `target_r_multiple`, which does
    # not exist, and every strategy errored out. That the sweep refused rather
    # than silently ignoring the unknown key is the behaviour worth keeping.
    "default": {
        "stop_atr_mult": [1.0, 1.4, 2.0],
        "target_r": [1.5, 2.0, 3.0],
    },
}

SYMBOL_FOR: dict[str, str] = {
    "equity": "RELIANCE",
    "crypto": "BTCUSDT",
    "us": "QQQ",
}
"""One liquid instrument per class. A sweep across a universe multiplies the
trial cost by the universe size for a question about parameters, not breadth.

`QQQ` is the US default because nine of the coded signals cite a study run on
**MNQ**, the Micro E-Mini Nasdaq 100 future. QQQ tracks the same index in cash
form: the instrument differs — no roll, no overnight margin, no futures tick —
but the underlying is the one the paper measured, which is nearer than any NSE
name and is stated rather than implied."""

SYMBOL_OVERRIDE: dict[str, str] = {
    # Zarattini, Barbon & Aziz test the opening range on a broad US equity
    # cross-section, not on an index. SPY is the cross-section's own benchmark
    # and the honest single-name stand-in; sweeping the actual 7,000 names
    # would multiply the trial cost by the universe for a question about two
    # parameters.
    "orb_in_play": "SPY",
}


def market_for(declaration: object) -> tuple[str, str]:
    """The asset class and symbol a strategy's own paper tested on.

    Read from `recommended_class` rather than from what is convenient to load.
    `futures` maps to the `us` reader because the futures cited are US index
    futures and what this platform holds is US cash bars on the same index —
    a substitution worth naming, which is why it happens here and not silently
    inside the loader.
    """
    strategy_id = str(getattr(declaration, "id", ""))
    asset_class = getattr(declaration, "asset_class", None)
    wanted = str(
        getattr(declaration, "recommended_class", None) or getattr(asset_class, "value", "")
    ).lower()

    if "crypto" in wanted:
        market = "crypto"
    elif "futures" in wanted or "us" in wanted.split() or strategy_id in SYMBOL_OVERRIDE:
        market = "us"
    else:
        market = "equity"

    return market, SYMBOL_OVERRIDE.get(strategy_id, SYMBOL_FOR[market])


def _write(
    sweeps: list[optimize.Sweep],
    *,
    before: int,
    after: int,
    start: dt.date,
    end: dt.date,
    record: bool,
    skipped: list[str],
    run_id: str,
    complete: bool,
) -> None:
    """Persist what has been swept so far. Safe to call after every strategy."""
    optimize_store.record(
        [
            optimize_store.Row(
                strategy_id=sweep.strategy_id,
                market=sweep.asset_class,
                symbol=sweep.symbol,
                candidates=len(sweep.candidates),
                best_pnl=sweep.best.net_pnl if sweep.best else 0.0,
                median_pnl=sweep.median_pnl,
                fills=sweep.best.fills if sweep.best else 0,
                win_rate=sweep.best.win_rate if sweep.best else 0.0,
                sessions=sweep.best.sessions if sweep.best else 0,
                best_params=dict(sweep.best.params) if sweep.best else {},
                settings=[
                    optimize_store.Setting(
                        params=dict(candidate.params),
                        net_pnl=candidate.net_pnl,
                        fills=candidate.fills,
                        wins=candidate.wins,
                        sessions=candidate.sessions,
                    )
                    for candidate in sweep.candidates
                ],
                error=sweep.error,
            )
            for sweep in sweeps
        ],
        trials_before=before,
        trials_after=after,
        required_t=sweeps[-1].required_t if sweeps else 0.0,
        start=start.isoformat(),
        end=end.isoformat(),
        dry_run=not record,
        skipped=skipped,
        run_id=run_id,
        complete=complete,
    )


def run(
    strategy_ids: Sequence[str],
    *,
    start: dt.date,
    end: dt.date,
    record: bool = True,
) -> list[optimize.Sweep]:
    from eulerlab.strategies import REGISTRY

    before = trials.count()
    print(f"trials spent before this run: {before}")
    print(
        f"{'strategy':22s} {'market':8s} {'symbol':7s} {'cands':>5} "
        f"{'best':>12} {'median':>12} {'fills':>6}"
    )
    print("-" * 80)

    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    run_id = f"{dt.datetime.now(dt.UTC).isoformat()}-{'dry' if not record else 'rec'}"
    out: list[optimize.Sweep] = []
    skipped: list[str] = []
    for strategy_id in strategy_ids:
        declaration = REGISTRY.get(strategy_id)
        if declaration is None:
            continue
        if strategy_id not in ALL_SIGNALS:
            # Not every registered strategy is an intraday bracket signal.
            # `tweezer_bottom` is a daily candlestick pattern with its own
            # engine, and it has no `stop_atr_mult` to sweep. Named in the
            # summary rather than printed as an error row: a strategy this
            # sweep cannot express is not a strategy that failed.
            skipped.append(strategy_id)
            continue
        # The paper's market, not ours.
        asset_class, symbol = market_for(declaration)

        sweep = optimize.sweep_intraday(
            strategy_id,
            symbol,
            asset_class=asset_class,
            space=SPACES["default"],
            start=start,
            end=end,
            record=record,
        )
        out.append(sweep)
        top = sweep.best
        print(
            f"{strategy_id:22s} {asset_class:8s} {symbol:7s} {len(sweep.candidates):>5} "
            f"{top.net_pnl if top else 0:>12,.0f} {sweep.median_pnl:>12,.0f} "
            f"{top.fills if top else 0:>6}"
            f"{'  ' + sweep.error if sweep.error else ''}",
            flush=True,
        )

        # Written now, not at the end. A half-hour sweep that only writes on
        # completion loses every finished strategy to one interruption, which
        # has happened three times.
        _write(
            out,
            before=before,
            after=trials.count(),
            start=start,
            end=end,
            record=record,
            skipped=skipped,
            run_id=run_id,
            complete=False,
        )

    after = trials.count()
    _write(
        out,
        before=before,
        after=after,
        start=start,
        end=end,
        record=record,
        skipped=skipped,
        run_id=run_id,
        complete=True,
    )

    print("-" * 80)
    if skipped:
        print(f"not swept (no intraday bracket form): {', '.join(skipped)}")
    print(f"trials spent by this run: {after - before}  (total {after})")
    if out:
        print(f"a result now needs t > {out[-1].required_t:.2f} to clear the noise bar")
        profitable = [s for s in out if s.best and s.best.net_pnl > 0]
        print(f"{len(profitable)} of {len(out)} had any profitable candidate")
        # Share of the best that sits above the median. `spread > 2 * |median|`
        # was the first form and it misreads a negative median: a strategy at
        # +20,499 against -1,993 has a best that is *entirely* tail, and that
        # test called it narrow. Reported the same way the Sweep tab reports it,
        # so the two do not disagree about the same run.
        wide = [s for s in out if s.best and s.best.net_pnl > 0 and s.spread > s.best.net_pnl * 0.5]
        print(
            f"{len(wide)} of {len(out)} had a best that is more than half tail — "
            "that gap is the sweep finding variance, not edge"
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.strategies import REGISTRY

    parser = argparse.ArgumentParser(prog="optimize")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--only", default="", help="comma-separated strategy ids")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate without recording trials — for checking the sweep, never for a result",
    )
    args = parser.parse_args(argv)

    if args.only:
        ids = [s.strip() for s in args.only.split(",") if s.strip()]
    else:
        ids = [d.id for d in REGISTRY.values() if not d.is_strategy_subclass]

    run(
        ids,
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
        record=not args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
