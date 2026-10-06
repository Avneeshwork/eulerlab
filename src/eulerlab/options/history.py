"""One row per trading day from a chain, for the options history tools.

OpenAlgo's straddle chart and option-Greeks chart both ask the same question
of a run of days: where was the at-the-money straddle, what implied vol did it
carry, and where was the forward. The chain endpoint already answers that for
one day; this reduces one day's answer to the handful of numbers a time series
needs, so the history endpoint can stay a loop over days.

Kept pure and separate from the server so it can be checked against a small
hand-built chain without parsing a bhavcopy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def history_point(chain: Mapping[str, Any]) -> dict[str, Any] | None:
    """The at-the-money straddle and its context for one chain payload.

    Returns None when the chain has no usable at-the-money row, so a day the
    forward could not be fitted is absent from the series rather than drawn as
    zero. The straddle needs both legs priced; the IV is the mean of the legs
    that solved, and is None when neither did.
    """
    if not chain.get("ok"):
        return None
    atm = _number(chain.get("atm_strike"))
    if atm is None:
        return None
    rows: Sequence[Mapping[str, Any]] = chain.get("strikes") or []
    row = next((r for r in rows if _number(r.get("strike")) == atm), None)
    if row is None:
        return None
    call = _number(row.get("call_price"))
    put = _number(row.get("put_price"))
    if call is None or put is None:
        return None

    vols = [v for v in (_number(row.get("call_iv")), _number(row.get("put_iv"))) if v is not None]
    ratio = chain.get("put_call_ratio") or {}
    pain = chain.get("max_pain") or {}
    return {
        "day": chain.get("day"),
        "expiry": chain.get("expiry"),
        "days_to_expiry": chain.get("days_to_expiry"),
        "forward": _number(chain.get("forward")),
        "atm_strike": atm,
        "call": call,
        "put": put,
        "straddle": call + put,
        "atm_iv": sum(vols) / len(vols) if vols else None,
        "pcr_oi": _number(ratio.get("by_open_interest")),
        "max_pain": _number(pain.get("strike")),
        # Untraded legs are NSE's settlement model, not a transaction, so the
        # series says so per point rather than mixing the two silently.
        "traded": bool(row.get("call_traded")) and bool(row.get("put_traded")),
    }
