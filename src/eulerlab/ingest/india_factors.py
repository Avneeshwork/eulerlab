"""Land the official IIMA Indian Fama-French + momentum CSV releases.

The IIMA site publishes CSV download links directly, so this fetches those
files rather than scraping rendered tables. Payloads are validated but stored
byte-for-byte in the append-only landing zone.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from datetime import date
from pathlib import Path

from eulerlab.ingest.landing import Landing, ManifestEntry

BASE_URL = "https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/DATA"
RELEASE = "2025-12"
RELEASE_DATE = date(2025, 12, 31)
LANDING = Landing(Path("data/landing/india_factors"))
USER_AGENT = "EulerLab research data fetch/1.0"

FILES = {
    "iima_daily_survivorship_adjusted": (
        f"{BASE_URL}/{RELEASE}_FourFactors_and_Market_Returns_Daily_SurvivorshipBiasAdjusted.csv"
    ),
    "iima_monthly_survivorship_adjusted": (
        f"{BASE_URL}/{RELEASE}_FourFactors_and_Market_Returns_Monthly_SurvivorshipBiasAdjusted.csv"
    ),
}
EXPECTED_COLUMNS = ("Date", "SMB", "HML", "WML", "MF", "RF")


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"IIMA factor download returned HTTP {response.status}")
        payload: bytes = response.read()
    _validate(payload)
    return payload


def _validate(payload: bytes) -> int:
    text = payload.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = tuple(next(reader, ()))
    if header != EXPECTED_COLUMNS:
        raise ValueError(f"Unexpected IIMA factor columns: {header!r}")
    rows = 0
    for line, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(EXPECTED_COLUMNS):
            raise ValueError(f"Malformed IIMA CSV row {line}: expected 6 fields, got {len(row)}")
        rows += 1
    if rows < 100:
        raise ValueError(f"IIMA factor file is unexpectedly short ({rows} rows)")
    return rows


def download() -> list[ManifestEntry]:
    """Fetch and immutably land both adjusted frequency files for the release."""
    entries: list[ManifestEntry] = []
    for segment, url in FILES.items():
        existing = LANDING.entries().get((RELEASE_DATE.isoformat(), segment))
        if existing and (LANDING.root / existing.path).exists():
            entries.append(existing)
            continue
        payload = _fetch(url)
        rows = _validate(payload)
        entries.append(
            LANDING.write(
                trade_date=RELEASE_DATE,
                segment=segment,
                file_format="csv",
                url=url,
                payload=payload,
                rows=rows,
                inner_name=Path(url).name,
                suffix="csv",
            )
        )
    return entries


if __name__ == "__main__":
    for landed in download():
        print(f"{landed.path} rows={landed.rows} sha256={landed.sha256}")
