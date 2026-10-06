"""`history_point` reduces one chain payload to one day of the straddle series."""

from __future__ import annotations

from typing import Any

from eulerlab.options.history import history_point


def _chain(**overrides: Any) -> dict[str, Any]:
    chain: dict[str, Any] = {
        "ok": True,
        "day": "2026-10-05",
        "expiry": "2026-10-09",
        "days_to_expiry": 4,
        "forward": 22_550.0,
        "atm_strike": 22_550.0,
        "strikes": [
            {"strike": 22_500.0, "call_price": 110.0, "put_price": 60.0},
            {
                "strike": 22_550.0,
                "call_price": 82.60,
                "put_price": 79.35,
                "call_iv": 0.12,
                "put_iv": 0.14,
                "call_traded": True,
                "put_traded": True,
            },
        ],
        "put_call_ratio": {"by_open_interest": 0.91},
        "max_pain": {"strike": 22_500.0},
    }
    chain.update(overrides)
    return chain


def test_straddle_is_the_sum_of_the_atm_legs() -> None:
    point = history_point(_chain())
    assert point is not None
    # 82.60 + 79.35, the ADR-055 straddle checked by hand.
    assert abs(point["straddle"] - 161.95) < 1e-9
    assert abs(point["atm_iv"] - 0.13) < 1e-12
    assert point["pcr_oi"] == 0.91
    assert point["max_pain"] == 22_500.0
    assert point["traded"] is True


def test_iv_uses_only_the_legs_that_solved() -> None:
    chain = _chain()
    chain["strikes"][1]["put_iv"] = None
    point = history_point(chain)
    assert point is not None and point["atm_iv"] == 0.12


def test_a_missing_leg_drops_the_day_rather_than_drawing_zero() -> None:
    chain = _chain()
    chain["strikes"][1]["put_price"] = None
    assert history_point(chain) is None


def test_no_atm_or_failed_chain_is_absent() -> None:
    assert history_point(_chain(atm_strike=None)) is None
    assert history_point(_chain(atm_strike=99_999.0)) is None
    assert history_point({"ok": False, "error": "no F&O bhavcopy"}) is None


def test_an_untraded_leg_is_flagged() -> None:
    chain = _chain()
    chain["strikes"][1]["put_traded"] = False
    point = history_point(chain)
    assert point is not None and point["traded"] is False
