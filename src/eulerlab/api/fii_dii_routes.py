"""`/api/fii-dii`: FII/DII provisional cash flows for the dashboard (ADR-088).

Read-only. It reads `data/derived/fii_dii_cash.jsonl`, which `make fii-dii`
appends to, through `fii_dii_cash.rows`, so nothing landed after the request
time can appear. A separate route from `/api/market-context` so the panel can
be moved or restyled without touching the other bands.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from eulerlab.ingest import fii_dii_cash

router = APIRouter(prefix="/api")


@router.get("/fii-dii")
def fii_dii() -> dict[str, Any]:
    return fii_dii_cash.summary(fii_dii_cash.rows())
