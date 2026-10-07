"""`make rebuild-ohlc` — add open, high and low to every day of the price panel.

The panel stored only the close until 2026-08-18 (`PanelRow.open`'s note): the
fields were added later, and a rebuild meant re-reading every cash bhavcopy —
2,900 downloads against B2's 2,500 a day. This reads them from NSE's own
archive instead, which has no such cap, through the same parser the panel
build uses (`quality.sources.bars_from_bhavcopy`), so a rebuilt day differs
from the stored day only by the three new fields.

It writes a separate file and is resumable: re-running skips the days already
rebuilt. `--swap` replaces the panel only after checking that every day's
closes match the stored panel exactly, keeping the old file beside it.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from eulerlab.features.panel import PANEL_PATH, cached_days

REBUILD_PATH = Path("data/derived/price_panel.ohlc.jsonl")
BACKUP_PATH = Path("data/derived/price_panel.close_only.jsonl")


def rebuild(*, min_interval: float = 0.3, limit: int | None = None) -> tuple[int, int]:
    """Returns (days written, days that could not be fetched)."""
    from eulerlab.corp_actions.prices import instrument_key
    from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
    from eulerlab.ingest.nse_urls import Segment, candidates
    from eulerlab.quality.sources import bars_from_bhavcopy

    wanted = sorted(cached_days(PANEL_PATH) - cached_days(REBUILD_PATH))
    if limit:
        wanted = wanted[:limit]
    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=min_interval))
    written = missing = 0
    REBUILD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REBUILD_PATH.open("a", encoding="utf-8") as handle:
        for index, trade_date in enumerate(wanted, start=1):
            day = date.fromisoformat(trade_date)
            payload = None
            for _fmt, url in candidates(day, Segment.CM):
                result = fetcher.get(url)
                if result.outcome is not Outcome.ABSENT and result.payload is not None:
                    payload = result.payload
                    break
            if payload is None:
                missing += 1
                continue
            for bar in bars_from_bhavcopy(payload, day):
                handle.write(
                    json.dumps(
                        {
                            "d": trade_date,
                            "s": bar.symbol,
                            "c": round(bar.close, 6),
                            "o": round(bar.open, 6),
                            "h": round(bar.high, 6),
                            "l": round(bar.low, 6),
                            "isin": instrument_key(bar.isin) or "",
                            "v": bar.volume,
                            "t": bar.turnover or 0.0,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            handle.flush()
            written += 1
            if index % 100 == 0:
                print(f"  {index}/{len(wanted)} days", flush=True)
    return written, missing


def _closes(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            out[row["d"]][row["s"]] = row["c"]
    return out


def check() -> list[str]:
    """Days where the rebuilt closes differ from the stored panel's."""
    stored, rebuilt = _closes(PANEL_PATH), _closes(REBUILD_PATH)
    problems = []
    for day, closes in stored.items():
        other = rebuilt.get(day)
        if other is None:
            problems.append(f"{day}: not rebuilt")
            continue
        missing = set(closes) - set(other)
        differing = [s for s in closes if s in other and abs(closes[s] - other[s]) > 1e-6]
        if missing or differing:
            problems.append(
                f"{day}: {len(missing)} symbols missing, {len(differing)} closes differ"
            )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rebuild-ohlc")
    parser.add_argument("--swap", action="store_true", help="check, then replace the panel")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.swap:
        written, missing = rebuild(limit=args.limit)
        print(f"rebuilt {written} days; {missing} could not be fetched -> {REBUILD_PATH}")
        return 1 if missing else 0

    problems = check()
    if problems:
        print(f"not swapping: {len(problems)} days differ from the stored panel")
        for line in problems[:20]:
            print(f"  {line}")
        return 1
    PANEL_PATH.replace(BACKUP_PATH)
    REBUILD_PATH.replace(PANEL_PATH)
    print(f"swapped: {PANEL_PATH} now has open/high/low; the close-only panel is {BACKUP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
