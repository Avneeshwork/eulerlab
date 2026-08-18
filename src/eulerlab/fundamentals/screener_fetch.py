"""Fetch and store screener.in company fundamentals.

See ADR-011 for the provenance decision. Politeness constraints kept regardless
of that decision, because they are engineering hygiene rather than legal
theatre: a real rate limit, bounded retries, a single thread, and a stop rather
than a push if the site starts refusing.

Storage mirrors the rest of the landing zone: one Parquet file per company per
fetch, an append-only manifest, atomic write-then-rename, and a `knowledge_time`
on every row. Fundamentals get *restated* — a company revises a prior quarter —
so keeping each fetch as its own dated snapshot rather than overwriting is what
makes point-in-time reconstruction possible later. Overwriting would quietly
destroy the ability to ask "what did we believe this number was in March?"
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from eulerlab.fundamentals.screener_parse import Cell, Profile, parse_page, parse_profile

BASE_URL = "https://www.screener.in/company/{symbol}/"
CONSOLIDATED_URL = "https://www.screener.in/company/{symbol}/consolidated/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

MIN_INTERVAL_S = 2.5
"""Deliberately slower than the exchange downloaders. This is a small site."""

MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ScreenerError(RuntimeError):
    """The page could not be fetched."""


class RefusedError(ScreenerError):
    """The site is actively refusing us — stop, do not push harder."""


@dataclass
class Fetched:
    symbol: str
    name: str | None
    consolidated: bool
    cells: list[Cell]
    html_bytes: int
    profile: Profile = field(default_factory=Profile)


class ScreenerClient:
    def __init__(self, *, min_interval_s: float = MIN_INTERVAL_S, seed: int = 0) -> None:
        self.min_interval_s = min_interval_s
        self._random = random.Random(seed)
        self._last = 0.0

    def _wait(self) -> None:
        gap = self.min_interval_s - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)

    def _get(self, url: str) -> str:
        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    self._last = time.monotonic()
                    body: bytes = response.read()
                    return body.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                self._last = time.monotonic()
                if exc.code in {401, 403}:
                    msg = f"refused with HTTP {exc.code} — stopping rather than retrying"
                    raise RefusedError(msg) from exc
                last = f"HTTP {exc.code}"
                if exc.code not in RETRYABLE_STATUS:
                    raise ScreenerError(last) from exc
            except Exception as exc:
                self._last = time.monotonic()
                last = f"{type(exc).__name__}: {exc}"

            if attempt < MAX_ATTEMPTS:
                delay = min(2.0 * (2.0 ** (attempt - 1)), 15.0)
                time.sleep(delay * (0.5 + self._random.random()))

        msg = f"{last} after {MAX_ATTEMPTS} attempts"
        raise ScreenerError(msg)

    def fetch(self, symbol: str, *, consolidated: bool = True) -> Fetched:
        url = (CONSOLIDATED_URL if consolidated else BASE_URL).format(symbol=symbol)
        page = self._get(url)
        cells = parse_page(page)
        if not cells and consolidated:
            # Many smaller companies publish standalone results only.
            page = self._get(BASE_URL.format(symbol=symbol))
            cells = parse_page(page)
            consolidated = False
        profile = parse_profile(page)
        return Fetched(
            symbol=symbol,
            name=profile.name,
            consolidated=consolidated,
            cells=cells,
            html_bytes=len(page),
            profile=profile,
        )


def _profile_cells(fetched: Fetched) -> list[Cell]:
    """Flatten profile facts into the same (section, label, period, value) shape.

    Sector, index membership and the header ratios have no reporting period, so
    they carry the fetch date as their period: they describe what was true when
    we looked, not what was true for some quarter.
    """
    out: list[Cell] = []
    for index, name in enumerate(fetched.profile.sectors):
        out.append(Cell("sector", f"level_{index + 1}", "", None, name))
    for name in fetched.profile.indices:
        out.append(Cell("index_membership", name, "", None, name))
    for label, raw in fetched.profile.ratios:
        out.append(Cell("top_ratios", label, "", None, raw))
    return out


def cells_to_table(fetched: Fetched, knowledge_time: str) -> pa.Table:
    fetched = Fetched(
        symbol=fetched.symbol,
        name=fetched.name,
        consolidated=fetched.consolidated,
        cells=[*fetched.cells, *_profile_cells(fetched)],
        html_bytes=fetched.html_bytes,
        profile=fetched.profile,
    )
    return pa.table(
        {
            "symbol": pa.array([fetched.symbol] * len(fetched.cells), pa.string()),
            "section": pa.array([c.section for c in fetched.cells], pa.string()),
            "row_label": pa.array([c.row_label for c in fetched.cells], pa.string()),
            "period": pa.array([c.period for c in fetched.cells], pa.string()),
            "value": pa.array([c.value for c in fetched.cells], pa.float64()),
            "raw": pa.array([c.raw for c in fetched.cells], pa.string()),
            "consolidated": pa.array([fetched.consolidated] * len(fetched.cells), pa.bool_()),
            "knowledge_time": pa.array([knowledge_time] * len(fetched.cells), pa.string()),
        }
    )


class FundamentalsStore:
    """Landing zone for fundamentals, one snapshot per company per fetch date."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / "manifest.jsonl"
        self._seen: set[str] | None = None

    def _keys(self) -> set[str]:
        if self._seen is None:
            self._seen = set()
            if self.manifest_path.exists():
                for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        key = json.loads(line).get("key")
                        if isinstance(key, str):
                            self._seen.add(key)
        return self._seen

    def has(self, symbol: str, fetch_date: str) -> bool:
        return f"{symbol}/{fetch_date}" in self._keys()

    def write(self, fetched: Fetched, fetch_date: str) -> Path:
        knowledge_time = datetime.now(UTC).isoformat()
        table = cells_to_table(fetched, knowledge_time)

        target = self.root / fetched.symbol / f"{fetch_date}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".parquet.part")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(target)

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "key": f"{fetched.symbol}/{fetch_date}",
                        "symbol": fetched.symbol,
                        "name": fetched.name,
                        "consolidated": fetched.consolidated,
                        "fetch_date": fetch_date,
                        "rows": table.num_rows,
                        "path": str(target.relative_to(self.root)),
                        "knowledge_time": knowledge_time,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        self._keys().add(f"{fetched.symbol}/{fetch_date}")
        return target
