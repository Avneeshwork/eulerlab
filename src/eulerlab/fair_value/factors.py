"""Readers and estimates for the landed IIMA Indian factor files."""

from __future__ import annotations

import csv
import hashlib
import io
import statistics
from functools import lru_cache
from itertools import pairwise
from typing import Any

TREE = "india_factors"
DAILY_SEGMENT = "iima_daily_survivorship_adjusted"
MONTHLY_SEGMENT = "iima_monthly_survivorship_adjusted"


def _read_latest(segment: str) -> tuple[str, str, list[dict[str, str]]]:
    from eulerlab.ingest import landing_reader

    paths = landing_reader.available(TREE, f"{segment}/*/*/*.csv")
    if not paths:
        raise FileNotFoundError(f"No IIMA factor file is held under {TREE}/{segment}")
    relative = max(paths)
    payload = landing_reader.read(relative)
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    if not rows or set(rows[0]) != {"Date", "SMB", "HML", "WML", "MF", "RF"}:
        raise ValueError(f"Unexpected IIMA factor schema in {relative}")
    return relative, hashlib.sha256(payload).hexdigest(), rows


FactorRow = tuple[str, float | None, float | None, float | None, float | None, float | None]
"""Date, then MF, SMB, HML, WML and RF as decimals (None where not published)."""


@lru_cache(maxsize=4)
def _cached(segment: str) -> tuple[str, str, tuple[FactorRow, ...]]:
    relative, digest, rows = _read_latest(segment)
    compact: list[FactorRow] = []
    for row in rows:
        values: list[float | None] = []
        for key in ("MF", "SMB", "HML", "WML", "RF"):
            raw = row.get(key, "").strip()
            try:
                values.append(None if not raw or raw.upper() == "NA" else float(raw) / 100)
            except ValueError:
                values.append(None)
        mf, smb, hml, wml, rf = values
        compact.append((row.get("Date", ""), mf, smb, hml, wml, rf))
    return relative, digest, tuple(compact)


def observations(frequency: str) -> dict[str, Any]:
    """Return a date-indexed factor series, converting percentage points to decimals."""
    segment = DAILY_SEGMENT if frequency == "daily" else MONTHLY_SEGMENT
    relative, digest, compact = _cached(segment)
    rows: dict[str, dict[str, float]] = {}
    for date, mf, smb, hml, wml, rf in compact:
        if not date:
            continue
        cells = {"MF": mf, "SMB": smb, "HML": hml, "WML": wml, "RF": rf}
        rows[date] = {key: value for key, value in cells.items() if value is not None}
    folders = relative.split("/")
    return {
        "release": "-".join(folders[-3:-1]),
        "path": relative,
        "sha256": digest,
        "rows": rows,
    }


def long_run_premia() -> dict[str, Any]:
    """Arithmetic annualized premiums from the full monthly history."""
    source = observations("monthly")
    factors: dict[str, list[float]] = {key: [] for key in ("MF", "SMB", "HML", "WML")}
    for row in source["rows"].values():
        for key in factors:
            if key in row:
                factors[key].append(row[key])
    premia = {key: statistics.fmean(values) * 12 for key, values in factors.items() if values}
    return {
        "premia": premia,
        "source": source["path"],
        "release": source["release"],
        "sha256": source["sha256"],
        "through": max(source["rows"], default=""),
        "observations": {key: len(values) for key, values in factors.items()},
    }


def estimate_betas(price_series: list[list[Any]]) -> dict[str, Any]:
    """Unshrunk OLS excess-return betas on up to five years of daily observations.

    The same regression is applied to every issuer. The WML column is available
    for research but excluded from cost of equity, as specified in the roadmap.
    """
    source = observations("daily")
    factors = source["rows"]
    closes = [(str(day), float(close)) for day, close in price_series if close and float(close) > 0]
    observations_: list[tuple[float, float, float, float]] = []
    for (_, prior), (day, close) in pairwise(closes):
        factor = factors.get(day)
        if not factor or any(key not in factor for key in ("MF", "SMB", "HML", "RF")):
            continue
        if prior <= 0:
            continue
        y = close / prior - 1 - factor["RF"]
        observations_.append((y, factor["MF"], factor["SMB"], factor["HML"]))
    observations_ = observations_[-1260:]
    if len(observations_) < 252:
        return {
            "betas": {"MF": 1.0, "SMB": 0.0, "HML": 0.0},
            "raw_betas": None,
            "observations": len(observations_),
            "source": source["path"],
            "release": source["release"],
            "sha256": source["sha256"],
            "fallback": True,
        }
    matrix = [[1.0, row[1], row[2], row[3]] for row in observations_]
    target = [row[0] for row in observations_]
    raw = _least_squares(matrix, target)
    if raw is None:
        return {
            "betas": {"MF": 1.0, "SMB": 0.0, "HML": 0.0},
            "raw_betas": None,
            "observations": len(observations_),
            "source": source["path"],
            "release": source["release"],
            "sha256": source["sha256"],
            "fallback": True,
        }
    estimated = {"MF": raw[1], "SMB": raw[2], "HML": raw[3]}
    return {
        "betas": estimated,
        "raw_betas": {"MF": raw[1], "SMB": raw[2], "HML": raw[3]},
        "alpha_daily": raw[0],
        "observations": len(observations_),
        "source": source["path"],
        "release": source["release"],
        "sha256": source["sha256"],
        "fallback": False,
    }


def _least_squares(matrix: list[list[float]], target: list[float]) -> list[float] | None:
    """Solve the small normal-equation system with partial pivoting."""
    width = len(matrix[0])
    augmented = [[0.0] * (width + 1) for _ in range(width)]
    for row, value in zip(matrix, target, strict=True):
        for i in range(width):
            augmented[i][width] += row[i] * value
            for j in range(width):
                augmented[i][j] += row[i] * row[j]
    for column in range(width):
        pivot = max(range(column, width), key=lambda i: abs(augmented[i][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [cell / scale for cell in augmented[column]]
        for other in range(width):
            if other == column:
                continue
            scale = augmented[other][column]
            augmented[other] = [
                cell - scale * pivot_cell
                for cell, pivot_cell in zip(augmented[other], augmented[column], strict=True)
            ]
    return [augmented[i][width] for i in range(width)]


def current_risk_free() -> dict[str, Any] | None:
    """Most recent held India 10-year yield from the platform's macro snapshots."""
    from eulerlab import macro

    readings = macro.series("INDIA 10Y", days=120)
    if not readings:
        return None
    at, percent = readings[-1]
    return {"rate": percent / 100, "as_of": at, "source": "TVC:IN10Y held macro snapshot"}
