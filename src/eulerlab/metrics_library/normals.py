"""What is normal for each market metric, recomputed from the data held (ADR-104).

The pages in `docs/METRICS/` carry a written "what is normal" line with the
date it was computed. Those lines age. This module recomputes the same ranges
from whatever is held now and writes them to `data/derived/metric_normals.json`
with a knowledge time, so:

- the assistant's `explain_metric` tool quotes today's range beside the page;
- the knowledge keeper flags a page whose written range has drifted.

Every figure is a percentile of a named window of held data, with the count of
values it rests on. Pure functions take the series; `compute` gathers them.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

OUT = Path("data/derived/metric_normals.json")
OPTIONS_CACHE = Path("data/cache/options_history.jsonl")
API = "http://127.0.0.1:8000"
POINTS = (5, 25, 50, 75, 95)


def spread(values: Sequence[float | None], window: str) -> dict[str, Any] | None:
    """Nearest-rank percentiles of the values held, with how many there were."""
    held = sorted(float(v) for v in values if isinstance(v, int | float))
    if not held:
        return None
    n = len(held)
    out: dict[str, Any] = {f"p{p}": round(held[min(n - 1, int(p / 100 * n))], 4) for p in POINTS}
    out["n"] = n
    out["window"] = window
    return out


def from_series(
    *,
    vix: Sequence[float],
    nifty_close: Sequence[float],
    nifty_pe_since_2021: Sequence[float],
    breadth: Mapping[str, Sequence[float]],
    positioning: Mapping[str, Sequence[float]],
    fii_net: Sequence[float],
    dii_net: Sequence[float],
    pcr: Sequence[float],
    atm_iv: Sequence[float],
) -> dict[str, dict[str, Any]]:
    """The normals, keyed by metric page id then by figure."""
    moves = [abs(b / a - 1) * 100 for a, b in pairwise(nifty_close) if a > 0]
    five = [sum(fii_net[i - 5 : i]) for i in range(5, len(fii_net) + 1)]
    figures: dict[str, dict[str, Any] | None] = {
        "india-vix.all": spread(vix, "every close held"),
        "india-vix.1y": spread(vix[-252:], "last 252 closes"),
        "index-returns.nifty_abs_1d_pct": spread(moves, "every day held"),
        "valuation.nifty_pe": spread(nifty_pe_since_2021, "since 2021-04-01"),
        "fii-dii-cash-flows.fii_net": spread(fii_net, "every day held"),
        "fii-dii-cash-flows.dii_net": spread(dii_net, "every day held"),
        "fii-dii-cash-flows.fii_net_5d": spread(five, "every 5-day window held"),
        "put-call-ratio.pcr_oi": spread(pcr, "option history cache"),
        "atm-implied-volatility.atm_iv": spread(atm_iv, "option history cache"),
    }
    for key, values in breadth.items():
        figures[f"breadth-above-average.{key}"] = spread(values, "breadth series (about a year)")
    for group, values in positioning.items():
        figures[f"participant-long-share.{group}"] = spread(
            [v * 100 for v in values], "positioning series (last 60 files)"
        )
    out: dict[str, dict[str, Any]] = {}
    for key, value in figures.items():
        if value is None:
            continue
        page, figure = key.split(".", 1)
        out.setdefault(page, {})[figure] = value
    return out


def _context() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{API}/api/market-context", timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body if isinstance(body, dict) else {}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {}


def _options(path: Path | None = None) -> tuple[list[float], list[float]]:
    """PCR and ATM IV per session. The cache can hold a day more than once; the last row wins."""
    path = path or OPTIONS_CACHE
    by_day: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            point = (json.loads(line) or {}).get("point") or {}
        except (ValueError, AttributeError):
            continue
        if isinstance(point, dict) and point.get("day"):
            by_day[str(point["day"])] = point
    days = [by_day[d] for d in sorted(by_day)]
    pcr = [float(p["pcr_oi"]) for p in days if isinstance(p.get("pcr_oi"), int | float)]
    iv = [float(p["atm_iv"]) for p in days if isinstance(p.get("atm_iv"), int | float)]
    return pcr, iv


def compute(now: datetime | None = None) -> dict[str, Any]:
    """Gather the series from held data and compute. Sections not held are left out."""
    from eulerlab import market_context
    from eulerlab.ingest import fii_dii_cash

    series = market_context.indices()
    nifty = series.get("Nifty 50", [])
    ctx = _context()
    breadth_series = ((ctx.get("breadth") or {}).get("series") or {}) if ctx else {}
    position_series = ((ctx.get("positioning") or {}).get("series") or {}) if ctx else {}
    flows = fii_dii_cash.rows()
    pcr, iv = _options()
    metrics = from_series(
        vix=[r.close for r in series.get("India VIX", [])],
        nifty_close=[r.close for r in nifty],
        nifty_pe_since_2021=[
            r.pe for r in nifty if r.pe is not None and r.day.isoformat() >= "2021-04-01"
        ],
        breadth={
            k: v
            for k, v in breadth_series.items()
            if k in ("above_20", "above_50", "above_200", "new_highs", "new_lows", "high_low_index")
        },
        positioning={k: v for k, v in position_series.items() if k != "days"},
        fii_net=[float(r["fii_net"]) for r in flows],
        dii_net=[float(r["dii_net"]) for r in flows],
        pcr=pcr,
        atm_iv=iv,
    )
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    left_out = [] if ctx else ["breadth and positioning (workbench API not running)"]
    # One snapshot: it describes the data as of when it was computed.
    return {"event_time": at, "knowledge_time": at, "metrics": metrics, "left_out": left_out}


def save(payload: Mapping[str, Any], path: Path | None = None) -> Path:
    path = path or OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or OUT
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def describe(page_id: str, payload: Mapping[str, Any]) -> str:
    """The live normals of one page as plain lines, or '' when none are held."""
    figures = (payload.get("metrics") or {}).get(page_id) or {}
    if not figures:
        return ""
    lines = [f"Live normal ranges (computed {payload.get('knowledge_time', '?')}):"]
    for name, f in sorted(figures.items()):
        lines.append(
            f"- {name}: median {f['p50']}, 25th-75th {f['p25']} to {f['p75']}, "
            f"5th-95th {f['p5']} to {f['p95']} ({f['n']} values, {f['window']})"
        )
    return "\n".join(lines)


def main() -> int:
    payload = compute()
    path = save(payload)
    count = sum(len(v) for v in payload["metrics"].values())
    print(f"metric normals: {count} figure(s) for {len(payload['metrics'])} page(s) -> {path}")
    for note in payload["left_out"]:
        print(f"  left out: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
