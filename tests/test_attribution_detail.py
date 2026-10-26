"""Detailed attribution (`attribution_detail.py`, research 115), on data with known answers."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from eulerlab import attribution_detail as ad
from eulerlab.features.panel import PanelRow

CLASSIFY = {"A": ("Tech", "Software"), "B": ("Banks", "Banks")}


def _days(n: int, start: date = date(2021, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def test_euler_risk_shares_add_up_to_the_whole() -> None:
    days = _days(300)
    rng = np.random.default_rng(7)
    pa = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
    pb = 100 * np.cumprod(1 + rng.normal(0, 0.02, 300))
    rebuilt: dict[str, Any] = {
        "days": days,
        "book": [{"A": 600.0, "B": 400.0}] * 300,
        "equity": [1000.0] * 300,
        "prices": {"A": dict(zip(days, pa, strict=True)), "B": dict(zip(days, pb, strict=True))},
    }
    found = ad.risk(rebuilt, CLASSIFY)
    assert found is not None
    assert sum(h["share_of_risk"] for h in found["holdings"]) == pytest.approx(1.0, abs=1e-3)
    assert {s["sector"] for s in found["sectors"]} == {"Tech", "Banks"}


def test_the_regression_recovers_known_exposures() -> None:
    rng = np.random.default_rng(3)
    market, momentum = rng.normal(0.01, 0.05, 120), rng.normal(0.005, 0.03, 120)
    y = 0.002 + 1.2 * market + 0.5 * momentum + rng.normal(0, 0.001, 120)
    fit = ad._ols(list(y), {"market": list(market), "momentum": list(momentum)})
    assert fit is not None
    assert fit["betas"]["market"] == pytest.approx(1.2, abs=0.01)
    assert fit["betas"]["momentum"] == pytest.approx(0.5, abs=0.01)
    assert fit["alpha_monthly"] == pytest.approx(0.002, abs=0.0005)
    assert fit["r_squared"] > 0.99


def _month_ends(months: int) -> list[date]:
    out, d = [], date(2021, 1, 31)
    for _ in range(months):
        out.append(d)
        nxt = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
        d = date(nxt.year + (nxt.month // 12), nxt.month % 12 + 1, 1) - timedelta(days=1)
    return out


def test_brinson_effects_link_to_the_active_return() -> None:
    """Allocation + selection + interaction, Carino-linked, equal the active return."""
    ends = _month_ends(13)
    rng = np.random.default_rng(11)
    pa, pb = [100.0], [100.0]
    for _ in ends[1:]:
        pa.append(pa[-1] * (1 + rng.normal(0.02, 0.05)))
        pb.append(pb[-1] * (1 + rng.normal(0.0, 0.04)))
    prices = {"A": dict(zip(ends, pa, strict=True)), "B": dict(zip(ends, pb, strict=True))}
    book, equity = [], []
    for i in range(len(ends)):
        value = 700.0 * pa[i] / pa[0] + 300.0 * pb[i] / pb[0]
        book.append({"A": 700.0 * pa[i] / pa[0], "B": 300.0 * pb[i] / pb[0]})
        equity.append(value)
    bench = {
        d.isoformat()[:7]: {
            "Tech": (0.5, rng.normal(0.01, 0.03)),
            "Banks": (0.5, rng.normal(0.01, 0.03)),
        }
        for d in ends[:-1]
    }
    found = ad.brinson(
        {"days": ends, "book": book, "equity": equity, "prices": prices}, bench, CLASSIFY
    )
    assert found is not None
    effects = found["allocation"] + found["selection"] + found["interaction"]
    assert effects == pytest.approx(found["active"], abs=1e-6)
    assert found["trading"] == pytest.approx(0.0, abs=1e-9), "held all month: nothing traded"


def test_the_book_is_rebuilt_from_the_fills() -> None:
    days = _days(5)
    rows = [
        PanelRow(day=d, symbol="ZZTEST", close=10.0 + i, volume=1.0, turnover=1e6)
        for i, d in enumerate(days)
    ]
    report = {
        "starting_cash": 1000.0,
        "orders": [
            {
                "day": days[1].isoformat(),
                "symbol": "ZZTEST",
                "side": "buy",
                "quantity": 50,
                "price": 11.0,
                "cost": 1.0,
            }
        ],
        "equity": {
            "days": [d.isoformat() for d in days],
            "values": [1000.0, 999.0, 1049.0, 1099.0, 1149.0],
        },
    }
    rebuilt = ad.rebuild(report, rows)
    assert rebuilt["rebuilt"] == pytest.approx([1000.0, 999.0, 1049.0, 1099.0, 1149.0])
    assert rebuilt["max_gap"] == pytest.approx(0.0, abs=1e-9)


def test_a_position_held_after_its_last_price_is_flagged_frozen() -> None:
    days = _days(40)
    prices = {"OLD": dict.fromkeys(days[:10], 50.0), "NEW": dict.fromkeys(days, 20.0)}
    book = [{"OLD": 500.0, "NEW": 500.0} for _ in days]
    found = ad.exposure({"days": days, "book": book, "equity": [900.0] * 40, "prices": prices})
    assert [f["symbol"] for f in found["frozen"]] == ["OLD"]
    assert found["invested_max"] == pytest.approx(1000 / 900, abs=1e-3), "over-invested is reported"
    assert not math.isnan(found["by_year"][0]["effective_holdings"] or 0.0)
