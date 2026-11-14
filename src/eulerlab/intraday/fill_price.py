"""What a fill would really cost: reference price, half spread and market impact (#119, ADR-190).

The rule engine fills at the official open and close with 2 bps of slippage a
side (A-030, S-025). The official open is the pre-open auction's price, and
until 3 Aug 2026 the official close was a 30-minute VWAP that no order could
get. Research 184 found H-0202's edge lived only in that auction print. So
every engine figure has been an upper bound. This module is the one function
the engine calls to price a fill when asked to:

    price = reference x (1 + side x extra / 10,000)
    extra = max(0, half spread + impact - the 2 bps already charged)

| Part | Where it comes from |
|---|---|
| reference | the official print by default; with minute bars (`MinuteReference`), the 09:15-09:20 VWAP for an open fill and the 15:10-15:20 VWAP for a close fill |
| half spread | the stock's median quoted half spread from the depth recorder (`data/landing/kite_depth`, Nifty 50 since it first ran), else a bucket by its 20-session mean traded value (A-146) |
| impact | k x daily volatility x sqrt(order value / 20-session mean traded value), k = 1 (A-147), to be calibrated from live-price paper and real fills |

`side` is +1 for a buy and -1 for a sell, so the price always moves against
the trade. The 2 bps every book already charges stays, so the total slippage
is the larger of 2 bps and the model, never their sum. Every screen run with a
model says so in `price_model`.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from datetime import time as clock
from functools import cached_property
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from eulerlab.intraday import daily_universe_screen as du
from eulerlab.paths import data_path

At = Literal["open", "close"]
CHARGED_BPS = 2.0
"""The slippage every book already charges a side (`cross_section.SLIPPAGE_BPS`)."""
LOOKBACK = 20
IMPACT_K = 1.0
HALF_SPREAD_BUCKETS: tuple[tuple[float, float], ...] = (
    (5e9, 1.5),  # ₹500 crore a day or more
    (1e9, 3.0),  # ₹100 crore
    (2.5e8, 6.0),  # ₹25 crore
    (5e7, 12.0),  # ₹5 crore
    (0.0, 25.0),
)
"""(20-session mean traded value at least, half spread in bps)."""
OPEN_WINDOW = (clock(9, 15), clock(9, 20))
CLOSE_WINDOW = (clock(15, 10), clock(15, 20))
OFFICIAL = "official open and close, 2 bps slippage a side"

# ASSUMPTION: A-146 — half spreads by traded-value bucket, until the depth recorder covers a stock.
# ASSUMPTION: A-147 — square-root impact with k = 1, until paper fills calibrate it.


def bucket_half_spread(mean_value: float) -> float:
    for floor, bps in HALF_SPREAD_BUCKETS:
        if mean_value >= floor:
            return bps
    return HALF_SPREAD_BUCKETS[-1][1]  # pragma: no cover - the last floor is zero


def impact_bps(
    order_value: float, mean_value: float, daily_vol: float, k: float = IMPACT_K
) -> float:
    """k x sigma x sqrt(Q / ADV), in bps. No traded value means no estimate: a large number."""
    if mean_value <= 0:
        return 100.0
    return k * daily_vol * math.sqrt(order_value / mean_value) * 1e4


def minute_vwap(candles: Sequence[Any], at: At) -> float | None:
    """The VWAP of a session's minute bars inside the open or close window, or None."""
    start, end = OPEN_WINDOW if at == "open" else CLOSE_WINDOW
    num = den = 0.0
    for c in candles:
        t = c.ts.time()
        if start <= t < end and c.volume > 0:
            price = (c.high + c.low + c.close) / 3
            num += price * c.volume
            den += c.volume
    return num / den if den > 0 else None


def measured_half_spreads(root: Path | None = None) -> dict[str, float]:
    """Each recorded stock's median quoted half spread in bps, from the depth recorder's parts."""
    folder = root if root is not None else data_path("landing/kite_depth")
    if not folder.exists():
        return {}
    import pyarrow.parquet as pq

    found: dict[str, list[float]] = {}
    for part in sorted(folder.glob("*/part-*.parquet")):
        table = pq.read_table(part, columns=["symbol", "bid1_price", "ask1_price"]).to_pydict()
        for symbol, bid, ask in zip(
            table["symbol"], table["bid1_price"], table["ask1_price"], strict=True
        ):
            if bid and ask and ask > bid > 0:
                found.setdefault(str(symbol), []).append((ask - bid) / (ask + bid) * 1e4)
    return {s: statistics.median(v) for s, v in found.items() if len(v) >= 100}


class MinuteReference:
    """Open and close VWAPs from minute bars, one symbol's candles read once."""

    def __init__(self, fetch: Callable[[str], Sequence[Any]] | None = None) -> None:
        if fetch is None:
            from eulerlab.intraday import store

            fetch = store.fetch
        self._fetch = fetch
        self._by_day: dict[str, dict[date, list[Any]]] = {}

    def __call__(self, symbol: str, day: date, at: At) -> float | None:
        if symbol not in self._by_day:
            from eulerlab.intraday import store

            try:
                candles = self._fetch(symbol)
            except Exception:  # no minute bars for it: the official print stands
                candles = []
            self._by_day[symbol] = {d: list(c) for d, c in store.by_session(candles)}
        return minute_vwap(self._by_day[symbol].get(day, []), at)


class PriceModel:
    """Prices fills on one engine's data. `engine.Engine(data, prices=PriceModel(data))`."""

    def __init__(
        self,
        data: Any,
        *,
        k: float = IMPACT_K,
        spreads: Mapping[str, float] | None = None,
        reference: Callable[[str, date, At], float | None] | None = None,
    ) -> None:
        self.data = data
        self.k = k
        self.spreads = dict(measured_half_spreads() if spreads is None else spreads)
        self.reference = reference
        self.fills = 0
        self.extra_bps: list[float] = []

    def describe(self) -> str:
        ref = "minute VWAP 09:15-09:20 / 15:10-15:20" if self.reference else "official open/close"
        return (
            f"modelled: reference {ref}; half spread from {len(self.spreads)} recorded stock(s), "
            f"else by traded value (A-146); impact {self.k} x daily vol x sqrt(order / 20-session "
            "mean value) (A-147); at least the 2 bps a side already charged"
        )

    @cached_property
    def _history(self) -> dict[str, tuple[list[date], list[float], list[float]]]:
        """Per symbol: its sessions, traded values and close-to-close returns (0 for the first)."""
        out = {}
        for symbol, bars in self.data.panel.items():
            days = sorted(bars)
            values = [float(bars[d].value) for d in days]
            rets = [0.0]
            for a, b in pairwise(days):
                ratio = bars[b].close / bars[a].close if bars[a].close > 0 else 1.0
                rets.append(ratio - 1.0 if du.SPLIT_LOW <= ratio <= du.SPLIT_HIGH else 0.0)
            out[symbol] = (days, values, rets)
        return out

    def liquidity(self, symbol: str, day: date) -> tuple[float, float]:
        """(20-session mean traded value, daily volatility) on the sessions before `day`."""
        days, values, rets = self._history.get(symbol, ([], [], []))
        i = bisect.bisect_left(days, day)
        lo = max(0, i - LOOKBACK)
        window = values[lo:i]
        moves = rets[max(1, lo) : i]
        mean = statistics.fmean(window) if window else 0.0
        vol = statistics.stdev(moves) if len(moves) > 1 else 0.02
        return mean, vol

    def extra(self, symbol: str, day: date, order_value: float) -> float:
        """Bps beyond the 2 already charged: half spread + impact - 2, never below 0."""
        mean, vol = self.liquidity(symbol, day)
        half = self.spreads.get(symbol, bucket_half_spread(mean))
        return max(0.0, half + impact_bps(order_value, mean, vol, self.k) - CHARGED_BPS)

    def __call__(self, symbol: str, day: date, side: int, at: str, order_value: float) -> float:
        """The fill price for a buy (+1) or sell (-1) of `order_value` at the open or close."""
        bar = self.data.panel[symbol][day]
        official = float(bar.open if at == "open" else bar.close)
        ref = (
            self.reference(symbol, day, "open" if at == "open" else "close")
            if self.reference
            else None
        )
        base = ref if ref is not None and ref > 0 else official
        extra = self.extra(symbol, day, order_value)
        self.fills += 1
        self.extra_bps.append(extra)
        return base * (1 + side * extra / 1e4)

    def report(self) -> dict[str, Any]:
        found = self.extra_bps
        return {
            "model": self.describe(),
            "fills": self.fills,
            "mean_extra_bps": round(statistics.fmean(found), 2) if found else None,
        }


# --- research 176 re-priced -----------------------------------------------------------------


def compare(
    specs: Mapping[str, Any], data: Any, model: PriceModel | None = None
) -> list[dict[str, Any]]:
    """Each rule screened twice on the same data: official prints, then the model."""
    from eulerlab.intraday import rule_engine

    model = model or PriceModel(data)
    plain, priced = rule_engine.Engine(data), rule_engine.Engine(data, prices=model)
    out = []
    for name, spec in specs.items():
        a, b = plain.screen(spec), priced.screen(spec)
        out.append(
            {
                "rule": name,
                "kind": spec.kind,
                "trades": a.get("count"),
                "net_bps_official": (a.get("per_bps") or {}).get("net_mean"),
                "net_bps_modelled": (b.get("per_bps") or {}).get("net_mean"),
                "sharpe_official": (a.get("net") or {}).get("sharpe"),
                "sharpe_modelled": (b.get("net") or {}).get("sharpe"),
                "passes_official": a.get("passes_screen"),
                "passes_modelled": b.get("passes_screen"),
            }
        )
    return out


def markdown(rows: Sequence[Mapping[str, Any]], model: PriceModel) -> str:
    head = [
        "# Research 176's rules re-priced (#119, ADR-190)",
        "",
        f"Model: {model.describe()}. Mean extra cost a fill: "
        f"{model.report()['mean_extra_bps']} bps over {model.fills} fills.",
        "",
        "| Rule | Kind | Trades | Net bps, official | Net bps, modelled | Sharpe, official | "
        "Sharpe, modelled | Passes, official | Passes, modelled |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    body = [
        f"| {r['rule']} | {r['kind']} | {r['trades']} | {r['net_bps_official']} | "
        f"{r['net_bps_modelled']} | {r['sharpe_official']} | {r['sharpe_modelled']} | "
        f"{r['passes_official']} | {r['passes_modelled']} |"
        for r in rows
    ]
    return "\n".join(head + body) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from eulerlab.intraday import rule_engine

    parser = argparse.ArgumentParser(prog="make reprice", description=__doc__)
    parser.add_argument("--minute", action="store_true", help="minute VWAPs as the reference")
    parser.add_argument("--k", type=float, default=IMPACT_K, help="the impact coefficient")
    args = parser.parse_args(argv)
    data = rule_engine.Data()
    model = PriceModel(data, k=args.k, reference=MinuteReference() if args.minute else None)
    text = markdown(compare(rule_engine.reference_specs(), data, model), model)
    target = data_path("derived/reprice.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
