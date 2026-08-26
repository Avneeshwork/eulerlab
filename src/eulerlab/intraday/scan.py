"""`make tweezer` — run the Tweezer Bottom setup over real minute data.

One symbol at a time, one session at a time. Within a session the detector is
handed a window ending at the candle being evaluated and nothing after it, so
the lookahead firewall holds the same way it does in the daily engine.

**Every rejection is counted.** A scan that reports only the trades cannot tell
you whether a filter is doing any work or whether it has quietly excluded
everything. The rejection histogram is the first thing to read.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from eulerlab.intraday import bracket, store
from eulerlab.intraday.tweezer import Plan, Rejected, Rules, detect

UNIVERSE_FILE = Path("config/universe_top250.txt")

UNIVERSES = {"nifty50": 50, "nifty100": 100, "nifty250": 250}
"""Index-sized slices of our own liquidity ranking — **not** index membership.

ADR-008 settled this: a published constituent list is only available as it
stands *today*, so using one across history is survivorship bias of the exact
kind Sprint 4 exists to prevent. The 2015 scan would be run on the companies
that survived to 2026.

So `nifty50` means "the 50 most-traded names as of the ranking date", which is a
liquidity proxy for the index rather than the index. The distinction matters
whenever a result is reported, and the scan prints it every time.
"""


def universe(name: str, *, path: Path = UNIVERSE_FILE) -> list[str]:
    """Resolve a universe name to symbols, longest-lived first."""
    key = name.lower().replace(" ", "").replace("-", "")
    if key not in UNIVERSES:
        msg = f"unknown universe {name!r}; try {', '.join(sorted(UNIVERSES))}"
        raise ValueError(msg)
    if not path.exists():
        msg = f"{path} is missing; the universe is derived from it"
        raise FileNotFoundError(msg)
    symbols = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return symbols[: UNIVERSES[key]]


@dataclass
class ScanResult:
    symbol: str
    sessions: int = 0
    candles: int = 0
    plans: int = 0
    trades: list[bracket.Trade] = field(default_factory=list)
    rejections: dict[str, int] = field(default_factory=dict)

    @property
    def filled(self) -> list[bracket.Trade]:
        return [t for t in self.trades if t.filled]

    def net_pnl(self) -> float:
        return sum(t.net_pnl() for t in self.filled)

    def costs(self) -> float:
        return sum(t.costs for t in self.filled)

    def wins(self) -> int:
        return sum(1 for t in self.filled if t.net_pnl() > 0)

    def render(self) -> str:
        lines = [
            f"\n{self.symbol}: {self.sessions} sessions, {self.candles:,} candles",
            f"  setups found   {self.plans}",
            f"  orders filled  {len(self.filled)}   (a stop-entry may never trigger)",
        ]
        if self.filled:
            wins = self.wins()
            rate = wins / len(self.filled) * 100.0
            r_values = [t.r_multiple() for t in self.filled]
            lines += [
                f"  win rate       {wins}/{len(self.filled)} = {rate:.0f}%",
                f"  net P&L        {self.net_pnl():>12,.0f}   after {self.costs():,.0f} of costs",
                f"  average R      {sum(r_values) / len(r_values):>12.2f}",
                f"  best / worst R {max(r_values):>7.2f} / {min(r_values):.2f}",
            ]
            reasons: dict[str, int] = {}
            for trade in self.filled:
                for leg in trade.exits:
                    reasons[leg.reason] = reasons.get(leg.reason, 0) + 1
            lines.append("  exits: " + ", ".join(f"{k} x{v}" for k, v in sorted(reasons.items())))
        else:
            lines.append("  no orders filled")

        if self.rejections:
            lines.append("\n  why candidates were refused (top 8):")
            top = sorted(self.rejections.items(), key=lambda kv: -kv[1])[:8]
            for reason, count in top:
                lines.append(f"    {count:>8,}  {reason}")
        return "\n".join(lines)


def scan_symbol(
    symbol: str,
    *,
    start: date,
    end: date,
    rules: Rules | None = None,
    equity: float = 1_000_000.0,
) -> ScanResult:
    rules = rules or Rules()
    candles = store.fetch(symbol, start=start, end=end)
    result = ScanResult(symbol=symbol, candles=len(candles))

    for _day, session in store.by_session(candles):
        result.sessions += 1
        warmup = max(rules.htf_sma_period, rules.adx_period * 2) + 2
        index = warmup
        while index < len(session) - 1:
            window = session[: index + 1]
            outcome = detect(window, rules, equity=equity)
            if isinstance(outcome, Rejected):
                result.rejections[outcome.reason] = result.rejections.get(outcome.reason, 0) + 1
                index += 1
                continue

            assert isinstance(outcome, Plan)
            result.plans += 1
            forward = session[index + 1 :]
            # NSE, stated rather than inherited. Tweezer only ever runs on
            # Indian equities, so this was correct while it was a default — and
            # correct-by-accident is how the same default went wrong in three
            # other call sites without anyone noticing.
            trade = bracket.run(outcome, forward, rules, asset_class="equity")
            result.trades.append(trade)
            # Skip past the trade so one setup cannot be counted many times as
            # the same pattern stays visible in successive windows.
            index += max(1, len(forward) if not trade.filled else 2)
        # a session ends flat; nothing carries overnight
    return result


def scan_many(
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
    rules: Rules | None = None,
    equity: float = 1_000_000.0,
    workers: int = 8,
    on_done: object = None,
) -> list[ScanResult]:
    """Scan a whole universe.

    Threaded because the work is dominated by waiting on B2, not by arithmetic.
    A symbol that fails is reported as an empty result rather than killing the
    run — one delisted name should not cost a 250-symbol scan.
    """
    rules = rules or Rules()

    def one(symbol: str) -> ScanResult:
        try:
            return scan_symbol(symbol, start=start, end=end, rules=rules, equity=equity)
        except Exception as exc:
            result = ScanResult(symbol=symbol)
            result.rejections[f"unavailable: {type(exc).__name__}"] = 1
            return result

    out: list[ScanResult] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(one, symbols):
            out.append(result)
            if callable(on_done):
                on_done(result, len(out), len(symbols))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for Tweezer Bottom setups.")
    parser.add_argument(
        "--universe",
        default="",
        help="nifty50 | nifty100 | nifty250 (liquidity-ranked, see ADR-008)",
    )
    parser.add_argument("--symbols", default="")
    parser.add_argument("--day", default="", help="scan a single session")
    parser.add_argument("--from", dest="start", default="2024-01-01")
    parser.add_argument("--to", dest="end", default="2024-06-30")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--quiet", action="store_true", help="totals only")
    parser.add_argument("--equity", type=float, default=1_000_000.0)
    parser.add_argument("--prune", action="store_true", help="delete the local cache when done")
    args = parser.parse_args(argv)

    if args.day:
        start = end = date.fromisoformat(args.day)
    else:
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    label = ""
    if args.universe:
        try:
            symbols = universe(args.universe)
        except (ValueError, FileNotFoundError) as exc:
            print(exc)
            return 2
        label = f"{args.universe} ({len(symbols)} names, liquidity-ranked — ADR-008)"
    else:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        label = f"{len(symbols)} named symbols"
    if not symbols:
        print("nothing to scan: pass --universe or --symbols")
        return 2

    print(f"scanning {label}")
    print(f"  {start} to {end}\n")

    def progress(result: ScanResult, done: int, total: int) -> None:
        if not args.quiet and (result.plans or done % 25 == 0 or done == total):
            mark = f"{result.plans} setup(s)" if result.plans else "-"
            print(f"  [{done:>3}/{total}] {result.symbol:<14} {mark}")

    results = scan_many(
        symbols,
        start=start,
        end=end,
        equity=args.equity,
        workers=args.workers,
        on_done=progress,
    )

    for result in results:
        if result.plans and not args.quiet:
            print(result.render())

    total_pnl = sum(r.net_pnl() for r in results)
    total_filled = sum(len(r.filled) for r in results)
    wins = sum(r.wins() for r in results)
    candles = sum(r.candles for r in results)
    unavailable = sum(1 for r in results if any(k.startswith("unavailable") for k in r.rejections))

    print(f"\n{'=' * 62}")
    print(f"{label}")
    print(f"  {start} to {end}   {candles:,} candles")
    print(f"  setups {sum(r.plans for r in results)}   filled {total_filled}   wins {wins}")
    print(f"  net {total_pnl:,.0f}")
    if unavailable:
        print(f"  {unavailable} symbol(s) had no minute data and were skipped")
    if 0 < total_filled < 20:
        print(
            f"\n  {total_filled} trades is far too few to read a win rate from. It says\n"
            f"  the setup is RARE, not that it works."
        )
    print(
        "\nThis spent no trial. It is not a validated result: one universe, one\n"
        "window. Run `make validate` if it ever becomes a candidate."
    )
    if args.prune:
        files, gigabytes = store.prune()
        print(f"\npruned {files:,} cached files ({gigabytes:.2f} GB); B2 keeps the originals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
