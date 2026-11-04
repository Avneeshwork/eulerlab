"""The stock screener's lists, as built by `make screener` (ADR-136)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from eulerlab import screener

router = APIRouter(prefix="/api")


@router.get("/screener")
def lists() -> dict[str, Any]:
    if not screener.OUT.exists():
        return {
            "ok": False,
            "error": "No screener built yet: `make screener` builds it after the daily data.",
        }
    try:
        return {"ok": True, **json.loads(screener.OUT.read_text(encoding="utf-8"))}
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "error": f"The screener file could not be read ({type(exc).__name__}).",
        }
