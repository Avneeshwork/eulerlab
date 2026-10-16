"""Telegram signals for deployments and for the registered gap strategy.

Operator, 2026-10-11: "setup telegram signals for paper / live trading
strategies like name of strategy and strategy actions". T-4043.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from eulerlab import notify
from eulerlab.deploy import signals
from eulerlab.deploy.deployments import Deployment
from eulerlab.research import gap_forecast as gf
from eulerlab.research import gap_signal


def _deployment(mode: str = "paper") -> Deployment:
    return Deployment(
        id="paper-india_sharpe_momentum_opt-2026-10-01-abc123",
        strategy_id="india_sharpe_momentum_opt",
        mode=mode,
        capital=100_000.0,
        start=date(2026, 10, 1),
        created_at="2026-10-07T16:06:39+00:00",
    )


FILLS = [
    {"day": "2026-10-05", "side": "buy", "quantity": 7, "symbol": "ATHERENERG", "price": 1410.6},
    {"day": "2026-10-09", "side": "sell", "quantity": 7, "symbol": "ATHERENERG", "price": 1434.4},
    {"day": "2026-10-09", "side": "buy", "quantity": 35, "symbol": "CUPID", "price": 310.26},
]

STATE: dict[str, Any] = {
    "status": "ok",
    "traded_through": "2026-10-09",
    "fills": FILLS,
    "equity": 102_017.11,
    "total_return": 0.0202,
    "cash": 8_991.53,
    "book": [{"symbol": "CUPID"}],
    "next_rebalance": "in 7 session(s)",
}


# --- deployments -------------------------------------------------------------------


def test_a_message_names_the_strategy_and_lists_only_the_new_orders() -> None:
    text = signals.message(_deployment(), {"traded_through": "2026-10-08"}, STATE)
    assert text is not None
    assert text.startswith("PAPER · Volatility-adjusted momentum, top 10"), "the library title"
    assert "Actions on 2026-10-09 (2):" in text
    assert "SELL 7 ATHERENERG @ 1,434.40" in text and "BUY  35 CUPID @ 310.26" in text
    assert "1,410.60" not in text, "the 5 Oct order was reported by an earlier run"
    assert "Equity ₹102,017 (+2.0%)" in text and "Next rebalance: in 7 session(s)" in text


def test_a_run_that_placed_nothing_sends_nothing() -> None:
    assert signals.message(_deployment(), {"traded_through": "2026-10-09"}, STATE) is None


def test_the_first_run_reports_every_order_so_far() -> None:
    text = signals.message(_deployment(), {}, STATE)
    assert text is not None and "Actions on 2026-10-05 to 2026-10-09 (3):" in text


def test_a_halt_is_reported_once() -> None:
    halted = {"status": "halted", "reason": "book and broker disagree on CUPID"}
    first = signals.message(_deployment(), {"status": "ok"}, halted)
    assert first is not None and "HALTED: book and broker disagree on CUPID" in first
    assert signals.message(_deployment(), {"status": "halted"}, halted) is None


def test_a_live_deployment_says_live() -> None:
    text = signals.message(_deployment("live"), {}, STATE)
    assert text is not None and text.startswith("LIVE · ")


def test_reported_gain_uses_invested_capital_after_cash_flows() -> None:
    text = signals.message(_deployment(), {}, {**STATE, "invested": 99_000.0, "equity": 102_017.0})
    assert text is not None and "gain ₹3,017" in text


def test_a_long_catch_up_is_capped() -> None:
    many = [
        {"day": "2026-10-09", "side": "buy", "quantity": 1, "symbol": f"S{i}"} for i in range(40)
    ]
    text = signals.message(_deployment(), {}, {**STATE, "fills": many})
    assert text is not None and "… and 15 more" in text and "(40)" in text


def test_announce_sends_through_notify_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def fake(text: str, **_: Any) -> notify.Delivery:
        sent.append(text)
        return notify.Delivery(True)

    monkeypatch.setenv("EULERLAB_TELEGRAM_SIGNALS", "1")
    monkeypatch.setattr(notify, "configured", lambda: True)
    monkeypatch.setattr(notify, "send", fake)
    result = signals.announce(_deployment(), {"traded_through": "2026-10-08"}, STATE)
    assert result is not None and result.sent and len(sent) == 1

    def boom(text: str, **_: Any) -> notify.Delivery:
        raise RuntimeError("network")

    monkeypatch.setattr(notify, "send", boom)
    failed = signals.announce(_deployment(), {"traded_through": "2026-10-08"}, STATE)
    assert failed is not None and not failed.sent and "network" in failed.reason


def test_it_is_off_in_tests_and_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "send", lambda *a, **k: pytest.fail("sent a real message"))
    assert signals.announce(_deployment(), {}, STATE) is None, "conftest switches signals off"


# --- the registered gap strategy --------------------------------------------------------


def test_the_gap_strategy_is_in_the_library_and_runnable() -> None:
    from eulerlab.api.server import STUDY_RUNNABLE
    from eulerlab.strategies import REGISTRY, AssetClass

    declared = REGISTRY[gf.CALM_RISE_ID]
    assert declared.title == gf.CALM_RISE_TITLE
    assert declared.asset_class is AssetClass.FUTURES and not declared.is_strategy_subclass
    assert declared.paper_url.endswith("53859.pdf") and len(declared.logic) == 4
    assert gf.CALM_RISE_ID in STUDY_RUNNABLE, "listed and not runnable would be half a registration"


def test_the_library_result_is_the_long_only_joint_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    from eulerlab.research.session_studies import Overnight

    monkeypatch.setattr(gf, "round_trip_cost", lambda day, price: 0.0)
    d0 = date(2026, 6, 1)
    days = [
        gf.Day(d0, 100, 102, 15, 14),  # green, calm: long tonight
        gf.Day(d0 + timedelta(days=1), 103, 101, 14, 16),  # red, fear: no trade
        gf.Day(d0 + timedelta(days=2), 102, 104, 16, 15),  # green, calm: long tonight
        gf.Day(d0 + timedelta(days=3), 103, 102, 15, 17),
    ]
    legs = [
        Overnight(days[1].day, 100.0, 101.0, 100.0, "2026-06-25"),  # +1%
        Overnight(days[2].day, 100.0, 90.0, 100.0, "2026-06-25"),  # not held
        Overnight(days[3].day, 100.0, 102.0, 100.0, "2026-06-25"),  # +2%
    ]
    payload = gf.calm_rise_payload(days, legs)
    assert payload["nights"] == 2 and payload["fills"] == 4
    assert payload["total_return"] == pytest.approx(1.01 * 1.02 - 1, abs=1e-6)
    assert payload["curve"] == pytest.approx([1.0, 1.01, 1.01, 1.01 * 1.02])
    assert (payload["asset_class"], payload["tier"]) == ("futures", "overnight")

    recent = gf.calm_rise_payload(days, legs, last_days=2)
    assert recent["nights"] == 1, "only signals from the last two sessions"


AT_1520 = datetime(2026, 10, 12, 9, 50, tzinfo=UTC)  # Monday 15:20 IST


def test_a_green_day_with_vix_down_says_buy_and_when_to_exit() -> None:
    text = gap_signal.compose(gap_signal.Live(22300.0, 22450.0, 15.2, 14.6), AT_1520)
    assert text.startswith(f"SIGNAL · {gf.CALM_RISE_TITLE}")
    assert "ACTION: BUY the near-month Nifty future at the close." in text
    assert "EXIT: SELL at tomorrow's open." in text
    assert "(GREEN)" in text and "(fell)" in text and "Not an order" in text
    assert "too late" not in text and "Run again" not in text


@pytest.mark.parametrize(
    "live",
    [
        gap_signal.Live(22300.0, 22200.0, 15.2, 14.6),  # red day
        gap_signal.Live(22300.0, 22450.0, 15.2, 15.9),  # green but VIX rose
        gap_signal.Live(22300.0, 22200.0, 15.2, 15.9),  # the paper's bearish signal: not traded
    ],
)
def test_anything_else_says_no_trade(live: gap_signal.Live) -> None:
    text = gap_signal.compose(live, AT_1520)
    assert "ACTION: none tonight" in text and "BUY" not in text


def test_the_message_says_when_it_was_read_too_early_or_too_late() -> None:
    live = gap_signal.Live(22300.0, 22450.0, 15.2, 14.6)
    assert gap_signal.timing(datetime(2026, 10, 12, 6, 0, tzinfo=UTC)) == "early"  # 11:30 IST
    assert gap_signal.timing(AT_1520) == "on time"
    assert gap_signal.timing(datetime(2026, 10, 12, 10, 5, tzinfo=UTC)) == "late"  # 15:35 IST
    assert gap_signal.timing(datetime(2026, 10, 11, 9, 50, tzinfo=UTC)) == "late"  # a Sunday
    assert "Run again nearer the close" in gap_signal.compose(
        live, datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    )
    assert "too late to act" in gap_signal.compose(live, datetime(2026, 10, 12, 10, 5, tzinfo=UTC))


# --- words the operator can send -----------------------------------------------------


def _one_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.deploy import deployments as store

    state = {
        **STATE,
        "fills_total": 3,
        "intended": {"names": ["CUPID", "HFCL"], "cut": ["RRKABEL"]},
    }
    state["book"] = [{"symbol": "CUPID", "quantity": 35, "value": 12813.5, "weight": 0.1248}]
    monkeypatch.setattr(store, "all_deployments", lambda: [_deployment()])
    monkeypatch.setattr(store, "read_state", lambda d: state)


def test_status_lists_each_deployment_with_its_strategy_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab import telegram_bot as bot

    _one_deployment(monkeypatch)
    text = bot.answer("/status")
    assert text.startswith("1. PAPER · Volatility-adjusted momentum, top 10")
    assert "₹102,017 (+2.0%) from ₹100,000" in text and "through 2026-10-09" in text
    assert bot.answer("status") == text, "the slash is optional"
    assert bot.answer("/status@EulerLabBot") == text, "as Telegram sends it in a group"


def test_positions_orders_and_next_take_a_deployment_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab import telegram_bot as bot

    _one_deployment(monkeypatch)
    assert "CUPID: 35 · ₹12,814 (12%)" in bot.answer("positions")
    assert "2026-10-09  BUY  35 CUPID @ 310.26" in bot.answer("orders 1")
    upcoming = bot.answer("next")
    assert (
        "Would hold: CUPID, HFCL" in upcoming and "Left out, capital too small: RRKABEL" in upcoming
    )
    assert "There is no deployment 5" in bot.answer("positions 5")
    assert "is not a number" in bot.answer("orders two")


def test_an_unknown_word_gets_the_list_and_every_word_is_in_it() -> None:
    from eulerlab import telegram_bot as bot

    reply = bot.answer("sell everything")
    assert reply.startswith("I do not know 'sell'.")
    for word in bot.COMMANDS:
        assert f"{word} — " in reply
    assert bot.answer("/start") == bot.help_text()


def test_no_word_can_place_change_or_stop_an_order() -> None:
    from eulerlab import telegram_bot as bot

    assert set(bot.COMMANDS) == {
        "status",
        "pnl",
        "positions",
        "orders",
        "next",
        "market",
        "movers",
        "price",
        "company",
        "news",
        "signal",
        "strategies",
        "results",
        "trials",
        "brief",
        "data",
        "jobs",
        "kite",
        "kill",
        "ask",
        "forget",
        "help",
    }, "a new word needs a decision recorded first: every word here is read-only (ADR-068)"


def test_only_the_operators_chat_is_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import telegram_bot as bot

    monkeypatch.setattr(notify, "_env", lambda name: "4242" if name == notify.CHAT_ENV else "tok")
    mine = {"message": {"chat": {"id": 4242}, "text": "help"}}
    theirs = {"message": {"chat": {"id": 9999}, "text": "help"}}
    assert bot.handle(mine) == bot.help_text()
    assert bot.handle(theirs) is None, "a stranger gets nothing, not even a refusal"
    assert bot.handle({"message": {"chat": {"id": 4242}, "photo": []}}) is None


def test_a_handler_that_breaks_answers_with_its_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import telegram_bot as bot

    def broken(_: str) -> str:
        raise RuntimeError("panel missing")

    monkeypatch.setitem(bot.COMMANDS, "status", bot.Command("x", broken, "Deployments"))
    assert bot.answer("status") == "status failed: RuntimeError: panel missing"
