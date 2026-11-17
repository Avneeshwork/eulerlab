"""Nifty and BankNifty futures rules on 15-minute bars (research 166).

Four pre-registered rules, decided on 15-minute closes and filled at the next
one-minute open, flat by the 15:25 open:

- **H-0099 / H-0100** the noise area (Zarattini, Aziz and Barbon; research
  071) on the Nifty and on BankNifty: long above the upper band, short below
  the lower, flat inside it.
- **H-0101** BankNifty opening-range breakout: the first 15-minute close
  outside the 09:15-09:29 range, stopped at the range's other side.
- **H-0102** Nifty gap fade: a gap of 0.40% or more whose first 15-minute bar
  turns back, traded toward the previous close.

The index minutes (`kite_index_minute`) stand in for the near-month future's
price (A-115). ₹10 lakh of notional a trade in continuous units; futures
charges from `costs.schedule` on the day plus 1 bp a side of slippage.
`make index-futures` writes `data/derived/index_futures.json`.
"""

from __future__ import annotations

import argparse
import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.options.strategies import _cost
from eulerlab.paths import data_path
from eulerlab.strategies.studies import research as rs

OUT = data_path("derived/index_futures.json")
INDEX = data_path("derived/index_history.jsonl")
NOTIONAL = 1_000_000.0
SLIPPAGE_BPS = 1.0
EXIT_MINUTE = 370
"""15:25: the open of this minute is the last fill."""
DECISIONS = tuple(range(29, 345, 15))
"""Closes of the 15-minute bars ending 09:45, 10:00, ... 15:00 (minutes after 09:15)."""
NOISE_DAYS = 14
GAP = 0.004
LATE = 5
"""The validation battery's late-entry stress: fill five minutes after the decision."""

NAMES = {"NIFTY50": "Nifty 50", "NIFTYBANK": "Nifty Bank"}


@dataclass(frozen=True)
class Trade:
    symbol: str
    day: date
    direction: int
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    reason: str

    @property
    def units(self) -> float:
        return NOTIONAL / self.entry

    @property
    def quantity(self) -> int:
        return round(self.units)

    @property
    def notional(self) -> float:
        return NOTIONAL

    @property
    def gross(self) -> float:
        return self.direction * (self.exit - self.entry) * self.units

    @property
    def costs(self) -> float:
        opening = Side.BUY if self.direction > 0 else Side.SELL
        closing = Side.SELL if self.direction > 0 else Side.BUY
        charges = _cost(self.day, Segment.FUTURES, opening, self.entry, self.units)
        charges += _cost(self.day, Segment.FUTURES, closing, self.exit, self.units)
        return charges + (self.entry + self.exit) * self.units * SLIPPAGE_BPS / 10_000


# --- data ------------------------------------------------------------------------------


def load_index(symbol: str, cutoff: date = cs.DATA_END) -> list[ip.Day]:
    """One index's one-minute bars from `kite_index_minute`; no file crossing the cutoff."""
    import pyarrow.parquet as pq

    from eulerlab.ingest import landing_reader

    rows: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    for name in sorted(landing_reader.available("kite_index_minute", f"{symbol}/*.parquet")):
        if rs._file_end(name) > cutoff:
            continue
        table = pq.read_table(
            io.BytesIO(landing_reader.read(name, cache=True)),
            columns=["ts", "open", "high", "low", "close"],
        )
        columns = [table.column(c).to_pylist() for c in table.column_names]
        for stamp, open_, high, low, close in zip(*columns, strict=True):
            if stamp is None or open_ is None or high is None or low is None or close is None:
                continue
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < ip.MINUTES:
                rows.setdefault(stamp[:10], {})[minute] = (
                    float(open_),
                    float(high),
                    float(low),
                    float(close),
                    0.0,
                )
    return [d for d in ip.days_from_rows(rows) if d.last >= EXIT_MINUTE]


def official_closes(symbol: str, path: Path = INDEX) -> dict[date, float]:
    name = NAMES[symbol]
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            bar = row["indices"].get(name) or {}
            if bar.get("c"):
                out[date.fromisoformat(row["d"])] = float(bar["c"])
    return out


def _previous(closes: Mapping[date, float], day: date) -> float | None:
    """The last official close strictly before `day`."""
    before = [d for d in closes if d < day]
    return closes[max(before)] if before else None


def _open(day: ip.Day, minute: int) -> tuple[int, float] | None:
    return day.fill_at(minute)


# --- the rules -------------------------------------------------------------------------


def noise_area(
    symbol: str, days: Sequence[ip.Day], closes: Mapping[date, float], *, delay: int = 0
) -> list[Trade]:
    """H-0099 / H-0100: the position is +1 above the band, -1 below, 0 inside."""
    out: list[Trade] = []
    prev_close = {d.day: _previous(closes, d.day) for d in days}
    for i in range(NOISE_DAYS, len(days)):
        day = days[i]
        before = prev_close[day.day]
        if before is None:
            continue
        anchor = day.close[0]
        history = days[i - NOISE_DAYS : i]
        upper_base, lower_base = max(anchor, before), min(anchor, before)
        held = 0
        entry: tuple[int, float] | None = None
        for m in DECISIONS:
            sigma = sum(abs(h.close[m] / h.close[0] - 1.0) for h in history) / NOISE_DAYS
            price = day.close[m]
            want = (
                1
                if price > upper_base * (1 + sigma)
                else -1
                if price < lower_base * (1 - sigma)
                else 0
            )
            if want == held:
                continue
            fill = _open(day, m + 1 + delay)
            if fill is None or fill[0] >= EXIT_MINUTE:
                break
            if held and entry is not None:
                out.append(
                    Trade(symbol, day.day, held, entry[0], entry[1], fill[0], fill[1], "band")
                )
            held, entry = want, (fill if want else None)
        if held and entry is not None:
            last = _open(day, EXIT_MINUTE)
            if last is not None:
                out.append(
                    Trade(symbol, day.day, held, entry[0], entry[1], last[0], last[1], "15:25")
                )
    return out


def _stopped(
    day: ip.Day, direction: int, start: int, stop: float, target: float | None
) -> tuple[int, float, str]:
    """Walk minutes from `start`: the stop first (conservative), then the target, else 15:25."""
    for m in range(start, EXIT_MINUTE):
        high, low, opened = day.high[m], day.low[m], day.open_[m]
        if high is None or low is None or opened is None:
            continue
        if direction > 0:
            if low <= stop:
                return m, min(opened, stop), "stop"
            if target is not None and high >= target:
                return m, max(opened, target), "target"
        else:
            if high >= stop:
                return m, max(opened, stop), "stop"
            if target is not None and low <= target:
                return m, min(opened, target), "target"
    last = _open(day, EXIT_MINUTE)
    assert last is not None  # days are kept only if they trade at 15:25
    return last[0], last[1], "15:25"


def opening_range(
    symbol: str, days: Sequence[ip.Day], closes: Mapping[date, float], *, delay: int = 0
) -> list[Trade]:
    """H-0101: the first 15-minute close outside 09:15-09:29, stopped at the other side."""
    del closes
    out: list[Trade] = []
    for day in days:
        span = day.span(0, 15)
        if span is None:
            continue
        high, low = span
        for m in DECISIONS[:-1]:
            price = day.close[m]
            direction = 1 if price > high else -1 if price < low else 0
            if not direction:
                continue
            fill = _open(day, m + 1 + delay)
            if fill is None or fill[0] >= EXIT_MINUTE:
                break
            stop = low if direction > 0 else high
            exit_minute, exit_price, why = _stopped(day, direction, fill[0], stop, None)
            out.append(
                Trade(symbol, day.day, direction, fill[0], fill[1], exit_minute, exit_price, why)
            )
            break
    return out


def gap_fade(
    symbol: str, days: Sequence[ip.Day], closes: Mapping[date, float], *, delay: int = 0
) -> list[Trade]:
    """H-0102: fade a 0.40% gap whose first 15-minute bar turned back; target the prior close."""
    out: list[Trade] = []
    for day in days:
        before = _previous(closes, day.day)
        span = day.span(0, 15)
        if before is None or span is None:
            continue
        anchor = day.close[0]
        gap = anchor / before - 1.0
        if abs(gap) < GAP:
            continue
        turned = day.close[14] < anchor if gap > 0 else day.close[14] > anchor
        if not turned:
            continue
        direction = -1 if gap > 0 else 1
        fill = _open(day, 15 + delay)
        if fill is None:
            continue
        stop = span[0] if direction < 0 else span[1]
        exit_minute, exit_price, why = _stopped(day, direction, fill[0], stop, before)
        out.append(
            Trade(symbol, day.day, direction, fill[0], fill[1], exit_minute, exit_price, why)
        )
    return out


Rule = Callable[..., list[Trade]]


@dataclass(frozen=True)
class Spec:
    hypothesis: str
    run_id: str
    symbol: str
    rule: Rule


SPECS: tuple[Spec, ...] = (
    Spec("H-0099", "nifty_futures_noise_area_15m", "NIFTY50", noise_area),
    Spec("H-0100", "banknifty_futures_noise_area_15m", "NIFTYBANK", noise_area),
    Spec("H-0101", "banknifty_futures_opening_range_15m", "NIFTYBANK", opening_range),
    Spec("H-0102", "nifty_futures_gap_fade_15m", "NIFTY50", gap_fade),
)
BY_ID = {spec.hypothesis: spec for spec in SPECS}


def validation_run(hypothesis: str) -> Any:
    """Trades as screened and filled five minutes late, for the battery (ADR-139)."""
    from eulerlab.validation.intraday import IntradayRun

    spec = BY_ID[hypothesis]
    days = load_index(spec.symbol)
    closes = official_closes(spec.symbol)
    return IntradayRun(
        spec.rule(spec.symbol, days, closes),
        spec.rule(spec.symbol, days, closes, delay=LATE),
        [d.day for d in days],
        NOTIONAL,
    )


def evaluate(spec: Spec, days: Sequence[ip.Day], closes: Mapping[date, float]) -> dict[str, Any]:
    book = spec.rule(spec.symbol, days, closes)
    sessions = [d.day for d in days]
    run = cs.report(
        spec.run_id,
        book,  # type: ignore[arg-type]  # same fields as cs.Trade
        sessions,
        params={
            "instrument": f"{spec.symbol} future, index minutes as its price (A-115)",
            "notional": NOTIONAL,
            "slippage_bps_a_side": SLIPPAGE_BPS,
            "decisions": "15-minute closes, filled at the next minute's open",
        },
        capital=NOTIONAL,
    )
    run["hypothesis"] = spec.hypothesis
    run["spent_trials"] = 0
    middle = sessions[len(sessions) // 2]
    run["halves_net_bps_total"] = [
        round(
            sum((t.gross - t.costs) for t in book if (t.day < middle) == first) / NOTIONAL * 1e4, 1
        )
        for first in (True, False)
    ]
    run["costs_bps_a_trade"] = (
        round(sum(t.costs for t in book) / len(book) / NOTIONAL * 1e4, 2) if book else None
    )
    run.pop("trade_log", None)
    return run


def run(output: Path = OUT) -> dict[str, Any]:
    loaded = {s: (load_index(s), official_closes(s)) for s in NAMES}
    result = {
        "research": "166",
        "runs": [evaluate(spec, *loaded[spec.symbol]) for spec in SPECS],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="index-futures")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for r in run(args.output)["runs"]:
        print(
            f"{r['hypothesis']} {r['id']}: {r['trades']} trades; gross "
            f"{r['per_trade_bps']['gross_mean']} bps, net {r['per_trade_bps']['net_mean']} bps a "
            f"trade (costs {r['costs_bps_a_trade']}); net Sharpe {r['net']['sharpe']}; "
            f"halves {r['halves_net_bps_total']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
