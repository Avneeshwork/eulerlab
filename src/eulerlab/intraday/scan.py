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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from eulerlab.intraday import bracket, store
from eulerlab.intraday.tweezer import Plan, Rejected, Rules, detect


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
            trade = bracket.run(outcome, forward, rules)
            result.trades.append(trade)
            # Skip past the trade so one setup cannot be counted many times as
            # the same pattern stays visible in successive windows.
            index += max(1, len(forward) if not trade.filled else 2)
        # a session ends flat; nothing carries overnight
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for Tweezer Bottom setups.")
    parser.add_argument("--symbols", default="RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK")
    parser.add_argument("--from", dest="start", default="2024-01-01")
    parser.add_argument("--to", dest="end", default="2024-06-30")
    parser.add_argument("--equity", type=float, default=1_000_000.0)
    parser.add_argument("--prune", action="store_true", help="delete the local cache when done")
    args = parser.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    total_pnl = 0.0
    total_filled = 0
    for symbol in symbols:
        result = scan_symbol(symbol, start=start, end=end, equity=args.equity)
        print(result.render())
        total_pnl += result.net_pnl()
        total_filled += len(result.filled)

    print(f"\n{'=' * 60}")
    print(f"{len(symbols)} symbols, {total_filled} filled trades, net {total_pnl:,.0f}")
    print(
        "\nThis spent no trial. It is not a validated result: one symbol set,\n"
        "one window, chosen by hand. Run `make validate` if it is ever a candidate."
    )
    if args.prune:
        files, gigabytes = store.prune()
        print(f"\npruned {files:,} cached files ({gigabytes:.2f} GB); B2 keeps the originals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
