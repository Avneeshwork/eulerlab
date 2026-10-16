"""The overnight future's paper book: the study's rule, through the real order path."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from eulerlab.deploy import deployments as store
from eulerlab.deploy import overnight
from eulerlab.deploy.runner import make_oms
from eulerlab.oms.states import OrderState
from eulerlab.research import gap_forecast as gf

START = date(2026, 10, 5)
EXPIRY = "2026-10-27"
LOT = 65


def _days(count: int) -> list[date]:
    out: list[date] = []
    day = START
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


DAYS = _days(5)
# Mon signals, Tue does not (RED), Wed signals, Thu does not (VIX up), Fri signals.
GREEN_CALM = [True, False, True, False, True]
CLOSE = [22000.0, 22100.0, 22050.0, 22200.0, 22300.0]
OPEN = [21950.0, 22110.0, 22000.0, 22150.0, 22250.0]  # each day's futures open


def _sessions() -> list[gf.Day]:
    out = []
    for day, calm in zip(DAYS, GREEN_CALM, strict=True):
        if calm:
            out.append(gf.Day(day, 100.0, 101.0, 15.0, 14.0))  # GREEN, VIX fell
        else:
            out.append(gf.Day(day, 101.0, 100.0, 14.0, 15.0))  # RED, VIX rose
    return out


def _futures(upto: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "d": day.isoformat(),
            "contracts": {
                EXPIRY: {"c": CLOSE[i], "o": OPEN[i]},
                "2026-11-24": {"c": CLOSE[i] + 100, "o": OPEN[i] + 100},
            },
        }
        for i, day in enumerate(DAYS[:upto])
    ]


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> store.Deployment:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    return store.create(gf.CALM_RISE_ID, mode="paper", capital=5_000_000.0, start=START)


def _replay(deployment: store.Deployment, upto: int = 5, **kw: Any) -> dict[str, Any]:
    return overnight.replay(
        deployment,
        make_oms(deployment),
        sessions=_sessions()[:upto],
        futures=_futures(upto),
        lots=kw.pop("lots", lambda day, expiry: LOT),
        traded_through=kw.pop("traded_through", None),
        cash_flows=kw.pop("cash_flows", None),
    )


def test_it_buys_at_the_close_of_a_signal_day_and_sells_at_the_next_open(
    deployment: store.Deployment,
) -> None:
    book = _replay(deployment)
    fills = [(f["day"], f["side"], f["quantity"]) for f in book["fills"]]
    # Whole lots up to the book's equity: 5,000,000 // (65 x 22,000) = 3 lots.
    assert fills == [
        (DAYS[0].isoformat(), "buy", 3 * LOT),
        (DAYS[1].isoformat(), "sell", 3 * LOT),
        (DAYS[2].isoformat(), "buy", 3 * LOT),
        (DAYS[3].isoformat(), "sell", 3 * LOT),
        (DAYS[4].isoformat(), "buy", 3 * LOT),
    ]
    assert {f["symbol"] for f in book["fills"]} == {f"NIFTY-FUT-{EXPIRY}"}
    # The last signal day has no next open yet: the position is open.
    assert book["held"] == {f"NIFTY-FUT-{EXPIRY}": 3 * LOT}
    assert book["position"]["day"] == DAYS[4] and book["signal_today"]


def test_the_money_is_the_overnight_move_less_costs(deployment: store.Deployment) -> None:
    book = _replay(deployment, upto=4)  # two complete round trips, nothing open
    quantity = 3 * LOT
    slip = deployment.slippage_bps / 10_000.0
    gross = 0.0
    for bought, sold in ((0, 1), (2, 3)):
        gross += quantity * (OPEN[sold] * (1 - slip) - CLOSE[bought] * (1 + slip))
    assert book["held"] == {} and book["position"] is None
    assert book["costs"] > 0
    assert book["equity"] == pytest.approx(deployment.capital + gross - book["costs"])
    assert book["curve"][-1] == [DAYS[3].isoformat(), round(book["equity"], 2)]
    assert sum(f["cost"] for f in book["fills"]) == pytest.approx(book["costs"], abs=0.05)


def test_a_replay_sends_nothing_twice_and_reads_the_same_book(
    deployment: store.Deployment,
) -> None:
    first = _replay(deployment, upto=3)
    assert first["sent"] == 3
    again = _replay(deployment, upto=3, traded_through=DAYS[2])
    assert again["sent"] == 0
    assert again["fills"] == first["fills"] and again["equity"] == first["equity"]
    # One more day of data: only the new exit is sent.
    later = _replay(deployment, upto=4, traded_through=DAYS[2])
    assert later["sent"] == 1 and later["fills"][-1]["side"] == "sell"
    oms = make_oms(deployment)
    assert all(state is OrderState.FILLED for state in oms.states().values())
    assert len(oms.states()) == 4


def test_overnight_flow_is_applied_before_the_next_close_sizing(
    deployment: store.Deployment,
) -> None:
    flow = {
        "amount": 100_000.0,
        "last_decided": DAYS[0].isoformat(),
        "entered_at": "flow-overnight",
    }
    book = _replay(deployment, cash_flows=[flow])

    assert book["flows"][0]["amount"] == 100_000
    assert book["flows"][0]["decision_day"] == DAYS[1]
    assert book["equity"] > deployment.capital + 100_000


def test_a_book_too_small_for_one_lot_never_trades_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    small = store.create(gf.CALM_RISE_ID, mode="paper", capital=100_000.0, start=START)
    book = _replay(small)
    assert book["fills"] == [] and book["sent"] == 0 and book["equity"] == 100_000.0
    assert len(book["rejections"]) == 3
    assert "capital too small" in book["rejections"][0]["reason"]
    assert "₹1,430,000" in book["rejections"][0]["reason"]  # 65 x 22,000


def test_a_missing_lot_size_skips_the_night_and_is_never_guessed(
    deployment: store.Deployment,
) -> None:
    book = _replay(deployment, upto=2, lots=lambda day, expiry: None)
    assert book["fills"] == [] and book["sent"] == 0
    assert book["rejections"][0]["reason"] == "lot size not found in that day's F&O file"


def test_a_signal_that_appears_for_a_day_already_traded_halts(
    deployment: store.Deployment,
) -> None:
    """Changed history must not put a trade in the past."""
    book = _replay(deployment, upto=2, traded_through=DAYS[1])
    assert "halt" in book and "history changed" in book["halt"]
    assert make_oms(deployment).states() == {}


def test_a_position_that_cannot_be_priced_at_the_open_halts(
    deployment: store.Deployment,
) -> None:
    futures = _futures(2)
    del futures[1]["contracts"][EXPIRY]["o"]
    book = overnight.replay(
        deployment,
        make_oms(deployment),
        sessions=_sessions()[:2],
        futures=futures,
        lots=lambda day, expiry: LOT,
        traded_through=None,
    )
    assert "halt" in book and "no opening price" in book["halt"]


def test_a_day_the_index_data_has_not_reached_is_not_judged_yet(
    deployment: store.Deployment,
) -> None:
    book = overnight.replay(
        deployment,
        make_oms(deployment),
        sessions=_sessions()[:2],  # the index file is a day behind the futures file
        futures=_futures(3),
        lots=lambda day, expiry: LOT,
        traded_through=None,
    )
    assert book["days"] == DAYS[:2]


def test_the_contract_is_the_nearest_one_alive_tomorrow() -> None:
    contracts = {"2026-10-27": {"c": 1.0}, "2026-11-24": {"c": 2.0}}
    assert overnight.contract_for(contracts, "2026-10-26") == ("2026-10-27", 1.0)
    # On its own expiry day the near contract is not alive tomorrow.
    assert overnight.contract_for(contracts, "2026-10-27") == ("2026-11-24", 2.0)
    assert overnight.contract_for({"2026-10-27": {"c": None}}, "2026-10-01") is None


def test_the_books_nights_are_the_studys_nights_on_real_history() -> None:
    """Where the data is on disk: the same signal nights and contracts as the study."""
    from eulerlab.market_history import NIFTY_FUTURES, _stored_days
    from eulerlab.research.gap_forecast_run import load_days
    from eulerlab.research.session_studies import futures_legs

    if not NIFTY_FUTURES.exists():
        pytest.skip("no futures history on this machine")
    sessions = load_days()
    signal = {s.day for s in sessions if gf.predict(gf.Model.JOINT, s) == gf.UP}
    stored = sorted(_stored_days(NIFTY_FUTURES), key=lambda d: str(d["d"]))[-260:]
    by_morning = {leg.day: leg for leg in futures_legs()}
    checked = 0
    for before, after in pairwise(stored):
        day = date.fromisoformat(str(before["d"]))
        chosen = overnight.contract_for(before["contracts"], str(before["d"]))
        leg = by_morning.get(date.fromisoformat(str(after["d"])))
        if day not in signal or chosen is None or leg is None:
            continue
        assert chosen == (leg.expiry, leg.previous_close)
        assert after["contracts"][chosen[0]]["o"] == leg.open
        checked += 1
    assert checked > 50


def test_the_whole_run_writes_a_state_the_screen_can_read_and_marks_an_open_position(
    deployment: store.Deployment, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import market_history
    from eulerlab.research import gap_forecast_run

    monkeypatch.setattr(gap_forecast_run, "load_days", _sessions)
    monkeypatch.setattr(market_history, "_stored_days", lambda path: _futures())
    monkeypatch.setattr(overnight, "lot_size", lambda day, expiry: LOT)

    state = overnight.run(deployment)
    assert state["status"] == "ok" and state["traded_through"] == DAYS[4].isoformat()
    assert state["fills_total"] == 5 and state["sent_this_run"] == 5
    row = state["book"][0]
    assert row["symbol"] == f"NIFTY-FUT-{EXPIRY}" and row["quantity"] == 3 * LOT
    # Marked at the close: down by the slippage paid on the way in, and the
    # last point of the curve says the same as the headline.
    slip = deployment.slippage_bps / 10_000.0
    realised = state["equity"] + 3 * LOT * CLOSE[4] * slip
    assert state["curve"][-1][1] == state["equity"]
    assert realised == pytest.approx(
        deployment.capital
        + sum(
            f["quantity"] * f["price"] * (1 if f["side"] == "sell" else -1)
            for f in state["fills"][:4]
        )
        - state["costs"],
        # The state rounds each fill price to the paisa; 195 units a fill.
        abs=5.0,
    )
    assert state["intended"]["names"] == [f"NIFTY-FUT-{EXPIRY}"]

    # A second run on the same data sends nothing and changes nothing that matters.
    again = overnight.run(deployment)
    assert again["sent_this_run"] == 0 and again["equity"] == state["equity"]
    assert again["fills"] == state["fills"]
