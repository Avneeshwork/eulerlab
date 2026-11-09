"""Likely movers: results due with their typical move, fresh reactions, breakouts (research 182)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from eulerlab import movers
from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow

IST = ZoneInfo("Asia/Kolkata")
DAYS = [date(2026, 1, 1) + timedelta(days=i) for i in range(300)]


def _rows(symbol: str, closes: list[float], volumes: list[float] | None = None) -> list[PanelRow]:
    vols = volumes or [1e5] * len(closes)
    return [
        PanelRow(day=d, symbol=symbol, close=c, volume=v, turnover=c * v, isin=f"IN-{symbol}")
        for d, c, v in zip(DAYS, closes, vols, strict=False)
    ]


def test_a_disclosure_after_the_close_reacts_the_next_session() -> None:
    days = DAYS[:5]
    assert movers.reaction_index(days, datetime(2026, 1, 2, 14, 0, tzinfo=IST)) == 1
    assert movers.reaction_index(days, datetime(2026, 1, 2, 16, 0, tzinfo=IST)) == 2
    assert movers.reaction_index(days, datetime(2026, 1, 5, 18, 0, tzinfo=IST)) is None


def test_typical_move_fresh_reaction_and_results_due() -> None:
    closes = [100.0] * 300
    # Three past reactions of 4%, 6% and -2%, then a +8% reaction on the last session.
    for i, r in ((50, 0.04), (120, 0.06), (190, -0.02)):
        closes[i:] = [c * (1 + r) for c in closes[i:]]
    closes[-1] = closes[-2] * 1.08
    rows = _rows("ABC", closes)
    when = [datetime.combine(DAYS[i], datetime.min.time(), IST) for i in (50, 120, 190, 299)]
    view = MarketView(as_of=DAYS[-1], history={"ABC": rows})
    table = {"ABC": {"sector": "Banks", "top_sector": True, "change_1m": 0.1}}
    got = movers.build(
        view,
        ["ABC"],
        table,
        upcoming=[{"symbol": "ABC", "meeting": "2026-11-12"}, {"symbol": "ZZZ", "meeting": "x"}],
        recent={"ABC": when[3:]},
        past={"ABC": tuple(when[:3])},
    )
    assert [d["symbol"] for d in got["results_due"]] == ["ABC"]
    # Median of 4%, 6%, 2% and the fresh 8%.
    assert abs(got["results_due"][0]["typical_move"] - 0.05) < 1e-3
    fresh = got["fresh_reactions"]
    assert fresh[0]["sessions_ago"] == 0 and fresh[0]["setups"][0].startswith("H-0187")
    # The 6% reaction 179 sessions ago is past the 60-session drift window.
    assert len(fresh) == 1
    assert got["gaps"] == []


def test_a_breakout_needs_a_new_high_on_twice_the_volume() -> None:
    closes = [100.0 + i * 0.01 for i in range(299)] + [110.0]
    quiet = _rows("A", closes, [1e5] * 300)
    loud = _rows("B", closes, [1e5] * 299 + [3e5])
    assert not movers.breakout_today(quiet)
    assert movers.breakout_today(loud)


def test_drift_picks_recent_reporters_that_beat_nifty_in_a_smooth_trend() -> None:
    up = [100.0 * 1.002**i for i in range(300)]
    up[290:] = [c * 1.04 for c in up[290:]]  # a +4% reaction 9 sessions before the last
    flat = [100.0] * 300
    view = MarketView(
        as_of=DAYS[-1],
        history={"UP": _rows("UP", up), "NIFTYBEES": _rows("NIFTYBEES", flat)},
    )
    when = {"UP": [datetime.combine(DAYS[290], datetime.min.time(), IST)]}
    got = movers.drift_picks(view, ["UP"], when)
    assert [d["symbol"] for d in got] == ["UP"] and got[0]["sessions_ago"] == 9
    assert got[0]["reaction"] > 0.04
    # Reported on the last session: too fresh for drift (2 sessions at least).
    late = {"UP": [datetime.combine(DAYS[299], datetime.min.time(), IST)]}
    assert movers.drift_picks(view, ["UP"], late) == []
