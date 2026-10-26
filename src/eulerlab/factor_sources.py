"""Public factor return data used by returns-based attribution."""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

US_FACTOR_CACHE = Path("data/derived/us_fama_french_monthly.json")
US_FACTOR_SOURCE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"
US_FACTOR_FILES = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip",
)
CACHE_SECONDS = 30 * 24 * 60 * 60
MONTH = re.compile(r"^\d{6}$")


def _parse_monthly(payload: bytes, required: set[str]) -> dict[str, dict[str, float]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
        if name is None:
            raise ValueError("factor archive contains no CSV")
        raw = archive.read(name).decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(raw)))
    header_i = next(
        (i for i, row in enumerate(rows) if required.issubset({cell.strip() for cell in row})),
        None,
    )
    if header_i is None:
        raise ValueError(f"factor archive is missing columns: {sorted(required)}")
    headers = [cell.strip() for cell in rows[header_i]]
    out: dict[str, dict[str, float]] = {}
    for row in rows[header_i + 1 :]:
        if not row:
            continue
        month = row[0].strip()
        if not MONTH.fullmatch(month) or len(row) < len(headers):
            continue
        try:
            values = {key: float(row[i].strip()) / 100.0 for i, key in enumerate(headers) if key}
        except (TypeError, ValueError):
            continue
        if any(value <= -0.99 for value in values.values()):
            continue
        out[month[:4] + "-" + month[4:]] = values
    if not out:
        raise ValueError("factor archive contains no monthly returns")
    return out


def _download() -> dict[str, Any]:
    request_headers = {"User-Agent": "EulerLab/1.0 returns attribution"}
    monthly: dict[str, dict[str, float]] | None = None
    for url, required in zip(
        US_FACTOR_FILES, ({"Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"}, {"Mom"}), strict=True
    ):
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=8) as response:
            parsed = _parse_monthly(response.read(), required)
        if monthly is None:
            monthly = parsed
        else:
            for month in monthly.keys() & parsed.keys():
                monthly[month]["Mom"] = parsed[month]["Mom"]
    if not monthly or not any("Mom" in row for row in monthly.values()):
        raise ValueError("factor archives do not share monthly observations")
    monthly = {month: row for month, row in monthly.items() if "Mom" in row}
    return {
        "source": US_FACTOR_SOURCE,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "latest_month": max(monthly),
        "monthly": monthly,
    }


def us_fama_french_monthly() -> dict[str, Any] | None:
    """Return cached U.S. FF5 + momentum monthly returns, refreshing monthly.

    Factor files are public, historical portfolio returns. No report data is
    sent to the source. If a refresh fails, a previously cached copy remains
    usable; if no cache exists, the caller can show an explicit coverage note.
    """
    cached: dict[str, Any] | None = None
    if US_FACTOR_CACHE.exists():
        try:
            cached = json.loads(US_FACTOR_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        age = time.time() - US_FACTOR_CACHE.stat().st_mtime
        if cached and age < CACHE_SECONDS:
            return cached
    try:
        refreshed = _download()
        US_FACTOR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        temporary = US_FACTOR_CACHE.with_suffix(".tmp")
        temporary.write_text(json.dumps(refreshed, separators=(",", ":")), encoding="utf-8")
        temporary.replace(US_FACTOR_CACHE)
        return refreshed
    except (OSError, ValueError, zipfile.BadZipFile):
        return cached
