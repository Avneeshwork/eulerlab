"""Five cash rules read from single-stock options (research 163).

Pre-registered as H-0088 to H-0092 before any run. Each signal is formed from
the NSE F&O bhavcopy after the close on t and traded on t+1, 09:20 to 15:10,
₹1 lakh a position, 1x, cash-intraday charges plus 2 bps a side, to 2024-11-29.
Stock prices and fills come from research 161's snapshots (`make minute-six`).

- **H-0088 skew** (Xing, Zhang and Zhao 2010): OTM put IV minus ATM call IV;
  short the top decile, buy the bottom.
- **H-0089 call-put spread** (Cremers and Weinbaum 2010): ATM call IV minus put
  IV; buy the top decile, short the bottom.
- **H-0090 IV changes** (An, Ang, Bali and Cakici 2014): change in call IV
  minus change in put IV; buy the top, short the bottom.
- **H-0091 put-call volume** (Pan and Poteshman 2006): put share of option
  volume; short the top, buy the bottom.
- **H-0092 volatility spread** (Bali and Hovakimian 2009): realised minus
  implied volatility; short the top, buy the bottom.

Implied volatility is Black-Scholes from the option's close where it traded,
S the stock's last cash close, r 6.5% (A-113), no dividends, on the nearest
expiry at least seven days away. `make option-iv` writes
`data/derived/option_iv.json`.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.paths import data_path
from eulerlab.strategies.studies import cash_five as five
from eulerlab.strategies.studies import minute_six as six
from eulerlab.strategies.studies import option_signal as sig
from eulerlab.strategies.studies import stock_fo as fo

OUT = data_path("derived/option_iv.json")
OPTIONS_DAILY = data_path("derived/stock_options_daily.jsonl")
RATE = 0.065  # ASSUMPTION: A-113
MIN_DAYS = 7
SKEW_TARGET, SKEW_LOW, SKEW_HIGH = 0.95, 0.90, 0.98
RV_DAYS = 20
YEAR = 252
SIGNALS = ("skew", "spread", "change", "put_share", "vol_spread")

Ranked = dict[date, list[tuple[float, str, five.Fill]]]
Chain = dict[str, Any]
"""{"x": expiry, "c": [[strike, close], ...], "p": [...], "cv": calls, "pv": puts}."""


# --- implied volatility ----------------------------------------------------------------


def _norm(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, years: float, vol: float, call: bool) -> float:
    root = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (RATE + vol * vol / 2.0) * years) / root
    d2 = d1 - root
    discount = strike * math.exp(-RATE * years)
    if call:
        return spot * _norm(d1) - discount * _norm(d2)
    return discount * _norm(-d2) - spot * _norm(-d1)


def implied_vol(price: float, spot: float, strike: float, years: float, call: bool) -> float | None:
    """Bisection between 1% and 300%; None when the price is outside that range."""
    low, high = 0.01, 3.0
    if (
        not bs_price(spot, strike, years, low, call)
        <= price
        <= bs_price(spot, strike, years, high, call)
    ):
        return None
    for _ in range(60):
        mid = (low + high) / 2.0
        if bs_price(spot, strike, years, mid, call) < price:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


# --- the bhavcopy, reduced to each stock's chosen expiry -------------------------------


def reduce_options(payload: bytes, day: str) -> dict[str, Any]:
    from eulerlab.master.derivatives import ContractType, parse_legacy_row, parse_udiff_row
    from eulerlab.options.chain import CLOSE_FIELDS, VOLUME_FIELDS, _number
    from eulerlab.options.nifty_history import _rows

    today = date.fromisoformat(day)
    found: dict[str, dict[date, list[tuple[float, str, float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in _rows(payload):
        contract = parse_udiff_row(row) or parse_legacy_row(row)
        if (
            contract is None
            or contract.contract_type is not ContractType.OPTION
            or contract.strike is None
            or contract.right is None
            or (contract.expiry - today).days < MIN_DAYS
        ):
            continue
        volume = _number(row, VOLUME_FIELDS) or 0.0
        close = _number(row, CLOSE_FIELDS) or 0.0
        found[contract.underlying][contract.expiry].append(
            (float(contract.strike), contract.right.value, close, volume)
        )
    chains = {}
    for symbol, by_expiry in found.items():
        expiry = min(by_expiry)
        rows = by_expiry[expiry]
        traded = [r for r in rows if r[3] > 0 and r[2] > 0]
        chains[symbol] = {
            "x": expiry.isoformat(),
            "c": sorted([k, c] for k, right, c, _ in traded if right == "CE"),
            "p": sorted([k, c] for k, right, c, _ in traded if right == "PE"),
            "cv": sum(r[3] for r in rows if r[1] == "CE"),
            "pv": sum(r[3] for r in rows if r[1] == "PE"),
        }
    return {"d": day, "o": chains}


def build_options_daily(path: Path = OPTIONS_DAILY, *, workers: int = 4) -> None:
    """Resumable: a day already in the file is not read again."""
    from eulerlab.ingest import landing_reader

    have = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            have = {json.loads(line[: line.index(",")] + "}")["d"] for line in handle}
    entries = {}
    for line in data_path("landing/nse/manifest.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") != "fo":
            continue
        day = entry["path"].rsplit("/", 1)[-1].split("_")[0]
        if fo.FO_FROM <= day <= cs.DATA_END.isoformat() and day not in have:
            entries[day] = f"nse/{entry['path']}"

    def fetch(day: str) -> dict[str, Any]:
        return reduce_options(landing_reader.read(entries[day], cache=False), day)

    path.parent.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(workers) as pool, path.open("a", encoding="utf-8") as out:
        for done, reduced in enumerate(pool.map(fetch, sorted(entries)), start=1):
            out.write(json.dumps(reduced, separators=(",", ":")) + "\n")
            out.flush()
            if done % 100 == 0:
                print(f"  options {done}/{len(entries)}", flush=True)


def load_options_daily(path: Path = OPTIONS_DAILY) -> dict[date, dict[str, Chain]]:
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            out[date.fromisoformat(row["d"])] = row["o"]
    return out


# --- signals ---------------------------------------------------------------------------


def atm(chain: Chain, spot: float, years: float) -> tuple[float, float, float] | None:
    """(strike, call IV, put IV) at the strike nearest spot where both traded."""
    calls = dict(chain["c"])
    puts = dict(chain["p"])
    common = sorted(set(calls) & set(puts), key=lambda k: (abs(k - spot), k))
    for strike in common[:1]:
        call = implied_vol(calls[strike], spot, strike, years, True)
        put = implied_vol(puts[strike], spot, strike, years, False)
        if call is not None and put is not None:
            return strike, call, put
    return None


def day_signals(
    chain: Chain, spot: float, today: date, realised: float | None
) -> dict[str, float | None]:
    out: dict[str, float | None] = dict.fromkeys(SIGNALS)
    total = chain["cv"] + chain["pv"]
    if total > 0:
        out["put_share"] = chain["pv"] / total
    years = (date.fromisoformat(chain["x"]) - today).days / 365.0
    middle = atm(chain, spot, years)
    if middle is None:
        return out
    _, call_iv, put_iv = middle
    out["spread"] = call_iv - put_iv
    if realised is not None:
        out["vol_spread"] = realised - (call_iv + put_iv) / 2.0
    otm = [
        (abs(k / spot - SKEW_TARGET), k, c)
        for k, c in chain["p"]
        if SKEW_LOW <= k / spot <= SKEW_HIGH
    ]
    if otm:
        _, strike, close = min(otm)
        put = implied_vol(close, spot, strike, years, False)
        if put is not None:
            out["skew"] = put - call_iv
    return out


def realised_vol(returns: Mapping[date, float], ordered: list[date], i: int) -> float | None:
    window = [returns[x] for x in ordered[max(0, i - RV_DAYS + 1) : i + 1] if x in returns]
    if len(window) < RV_DAYS - 5:
        return None
    mean = sum(window) / len(window)
    return math.sqrt(sum((r - mean) ** 2 for r in window) / (len(window) - 1) * YEAR)


def rankings(snaps: six.Snaps, options: Mapping[date, Mapping[str, Chain]]) -> dict[str, Ranked]:
    """Each signal formed on t, ranked on the stock's next session with its 09:20 fill."""
    out: dict[str, Ranked] = {name: defaultdict(list) for name in SIGNALS}
    for symbol, days in snaps.items():
        ordered = sorted(days)
        returns = fo.daily_returns(days)
        last_iv: tuple[float, float] | None = None
        for i in range(len(ordered) - 1):
            today, tomorrow = ordered[i], ordered[i + 1]
            chain = options.get(today, {}).get(symbol)
            spot = days[today].last_close
            if chain is None or spot < cs.MIN_PRICE:
                last_iv = None
                continue
            signals = day_signals(chain, spot, today, realised_vol(returns, ordered, i))
            spread = signals["spread"]
            if spread is not None:
                years = (date.fromisoformat(chain["x"]) - today).days / 365.0
                middle = atm(chain, spot, years)
                assert middle is not None
                now = (middle[1], middle[2])
                if last_iv is not None:
                    signals["change"] = (now[0] - last_iv[0]) - (now[1] - last_iv[1])
                last_iv = now
            else:
                last_iv = None
            nxt = days[tomorrow]
            if (tomorrow - today).days > 7 or nxt.entry < cs.MIN_PRICE:
                continue
            fill = five.Fill(
                six.DAY_START, 1, nxt.entry_minute, nxt.entry, nxt.exit_minute, nxt.exit
            )
            for name, value in signals.items():
                if value is not None:
                    out[name][tomorrow].append((value, symbol, fill))
    return out


# --- running ---------------------------------------------------------------------------

RULES = (
    ("H-0088", "skew", "nse_option_skew", -1),
    ("H-0089", "spread", "nse_call_put_iv_spread", 1),
    ("H-0090", "change", "nse_iv_change_spread", 1),
    ("H-0091", "put_share", "nse_put_call_volume", -1),
    ("H-0092", "vol_spread", "nse_realised_minus_implied", -1),
)


def run(output: Path = OUT) -> dict[str, Any]:
    build_options_daily()
    snaps, window = fo.load_snaps()
    options = load_options_daily()
    ranked = rankings(snaps, options)
    runs = [
        {
            "hypothesis": hypothesis,
            "days_with_100_names": sum(1 for v in ranked[name].values() if len(v) >= sig.MIN_NAMES),
            **sig._deciles(run_id, ranked[name], window, top_direction=direction),
        }
        for hypothesis, name, run_id, direction in RULES
    ]
    result = {
        "research": "docs/RESEARCH/163-stock-option-signals.md",
        "universe": len(snaps),
        "option_days": len(options),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="option-iv")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = run(args.output)
    for one in result["runs"]:
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades "
            f"({one['days_with_100_names']} days with 100 names); "
            f"{one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net a trade; net Sharpe {one['net']['sharpe']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
