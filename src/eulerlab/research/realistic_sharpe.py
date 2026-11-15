"""The Sharpe at fills a real order could get, kept beside the gate's (ADR-205).

The rule engine fills a daily intraday card at the official open and close. The
open is the pre-open auction's print and, until 3 Aug 2026, the close was a
30-minute VWAP no order could get (research 184). So the gate's Sharpe for those
cards is an upper bound: H-0202 gates at 12.75 and makes -0.32 when the same
trades enter at the 09:25 bar and exit at the 15:10 bar with the spread and
impact model (`logs/audit-2026-11-15/audit.py reprice`).

This module turns that audit, and the gate's own results, into one figure per
card for the Strategies list to lead with:

| Card | Realistic Sharpe |
|---|---|
| daily intraday (fills at the official open and close) | the reprice's `sharpe_executable`: 09:25 -> 15:10, gate costs plus spread and impact, 2018-11 to 2024-11, stocks with minute bars only |
| swing, minute and portfolio cards | the gate's own Sharpe; their fills are already ones an order can get |

The gate's evidence is never rewritten. The figures live in their own file
(`data/derived/realistic_sharpe.json`), written by `make realistic-sharpe`, and
the API attaches them to each row beside the stored Sharpe.

`shift_to` serves the page's luck bar (ADR-205): a repriced strategy's daily
returns move down by a constant so their Sharpe equals the realistic one. A
constant shift keeps every correlation, so the family clustering is unchanged;
it assumes the cost of a realistic fill is a level, not a new source of
variance (A-158).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from eulerlab.paths import data_path

TRADING_DAYS = 252.0

Basis = Literal["0925_1510_spread_impact", "gated"]


class Figure(BaseModel):
    """One card's realistic Sharpe, and the official-fill one it replaces as headline."""

    id: str
    sharpe: float
    basis: Basis
    label: str
    window: str
    coverage: float | None = None
    official_sharpe: float | None = None
    official_window: str = ""
    gate_sharpe: float | None = None
    gate_window: str = ""
    verdict: str = ""


def path() -> Path:
    return data_path("derived", "realistic_sharpe.json")


def _window(row: Mapping[str, Any]) -> str:
    first, last = row.get("first"), row.get("last")
    return f"{first}..{last}" if first and last else ""


def final_gated(
    first_pass: Iterable[Mapping[str, Any]],
    minute_2018: Iterable[Mapping[str, Any]] = (),
    at_1x: Iterable[Mapping[str, Any]] = (),
    portfolio: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """Each card's final gated run: 1x over the 2018 minute window over the first pass.

    The same order as `logs/rebacktest-2026-11-15/final_ranking.py`; the portfolio
    cards (H-0251 to H-0253) come from their own 2005-2024 runs, later lines winning.
    """
    out: dict[str, dict[str, Any]] = {}
    for rows in (first_pass, minute_2018, at_1x, portfolio):
        for row in rows:
            out[str(row["id"])] = dict(row)
    return out


def build(
    gated: Mapping[str, Mapping[str, Any]], reprice: Iterable[Mapping[str, Any]]
) -> dict[str, Figure]:
    """One figure per card that has a gated Sharpe. A repriced intraday card leads with its reprice."""
    repriced = {str(r["id"]): r for r in reprice if not r.get("error")}
    out: dict[str, Figure] = {}
    for card, row in sorted(gated.items()):
        gate_sharpe = row.get("sharpe")
        if gate_sharpe is None:
            continue
        verdict = str(row.get("verdict") or "")
        again = repriced.get(card)
        if again and again.get("kind") == "intraday" and again.get("sharpe_executable") is not None:
            out[card] = Figure(
                id=card,
                sharpe=float(again["sharpe_executable"]),
                basis="0925_1510_spread_impact",
                label="09:25 entry, 15:10 exit, gate costs plus spread and impact",
                window=str(again.get("window") or ""),
                coverage=again.get("coverage"),
                official_sharpe=again.get("sharpe_official"),
                official_window=str(again.get("window") or ""),
                gate_sharpe=float(gate_sharpe),
                gate_window=_window(row),
                verdict=verdict,
            )
            continue
        out[card] = Figure(
            id=card,
            sharpe=float(gate_sharpe),
            basis="gated",
            label="the gate's own Sharpe; these fills are ones an order can get",
            window=_window(row),
            official_sharpe=float(gate_sharpe),
            official_window=_window(row),
            gate_sharpe=float(gate_sharpe),
            gate_window=_window(row),
            verdict=verdict,
        )
    return out


def write(figures: Mapping[str, Figure], target: Path | None = None) -> Path:
    target = target or path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {card: figures[card].model_dump() for card in sorted(figures)}
    target.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return target


_CACHE: dict[tuple[str, int], dict[str, Figure]] = {}


def load(source: Path | None = None) -> dict[str, Figure]:
    """The stored figures, empty when `make realistic-sharpe` has not run. Cached on mtime."""
    source = source or path()
    try:
        stamp = source.stat().st_mtime_ns
    except OSError:
        return {}
    key = (str(source), stamp)
    if key not in _CACHE:
        raw = json.loads(source.read_text(encoding="utf-8"))
        _CACHE.clear()
        _CACHE[key] = {card: Figure.model_validate(body) for card, body in raw.items()}
    return _CACHE[key]


def shift_to(returns: Mapping[date, float], target: float) -> dict[date, float]:
    """The same daily returns moved by one constant so their annualised Sharpe is `target`."""
    values = list(returns.values())
    if len(values) < 2:
        return dict(returns)
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
    if sd == 0:
        return dict(returns)
    delta = target * sd / math.sqrt(TRADING_DAYS) - mean
    return {day: value + delta for day, value in returns.items()}


def _jsonl(file: Path) -> list[dict[str, Any]]:
    if not file.exists():
        return []
    return [
        json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="make realistic-sharpe", description=__doc__)
    parser.add_argument("--rebacktest", default="logs/rebacktest-2026-11-15")
    parser.add_argument("--reprice", default="logs/audit-2026-11-15/reprice.jsonl")
    args = parser.parse_args(argv)
    runs = Path(args.rebacktest)
    portfolio = _jsonl(runs / "results-portfolio.jsonl") + _jsonl(
        runs / "results-portfolio-cashyield.jsonl"
    )
    gated = final_gated(
        _jsonl(runs / "results.jsonl"),
        _jsonl(runs / "results-minute2018.jsonl"),
        _jsonl(runs / "results-1x.jsonl"),
        portfolio,
    )
    figures = build(gated, _jsonl(Path(args.reprice)))
    target = write(figures)
    repriced = sum(1 for f in figures.values() if f.basis != "gated")
    print(f"{len(figures)} cards, {repriced} repriced, written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
