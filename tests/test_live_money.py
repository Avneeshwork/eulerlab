"""The H-0194 real-money book (ADR-162): sizing, arming, picks, the loss cap, exits.

No test reaches Angel One or the machine's kill switch: a fake desk and a kill
switch under tmp_path stand in for both.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from eulerlab.deploy import live_money as lm
from eulerlab.oms.killswitch import KillSwitch, KillSwitchTripped

IST = timezone(timedelta(hours=5, minutes=30))
DAY = date(2026, 11, 10)


@pytest.fixture
def switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KillSwitch:
    s = KillSwitch(tmp_path / "KILL", tmp_path / "kill.log")
    monkeypatch.setattr(lm, "_switch", lambda: s)
    monkeypatch.setattr(lm, "is_session", lambda d: d.weekday() < 5)
    monkeypatch.setattr(lm, "_sleep", lambda _s: None)
    return s


def settings(**kw: Any) -> lm.Settings:
    return lm.Settings(**{"capital": 1000.0, "leverage": 5.0, "loss_cap": 150.0, **kw})


def quote(open_: float, bid: float, ask: float) -> dict[str, Any]:
    return {
        "ohlc": {"open": open_},
        "last_price": (bid + ask) / 2,
        "depth": {"buy": [{"price": bid}], "sell": [{"price": ask}]},
    }


class FakeDesk:
    def __init__(self, quotes: dict[str, dict[str, Any]], switch: KillSwitch) -> None:
        self._quotes = quotes
        self.switch = switch
        self.held: dict[str, int] = {}
        self.sent: list[tuple[str, str, bool, int]] = []
        self.views: dict[str, dict[str, Any]] = {}

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {s: self._quotes[s] for s in symbols if s in self._quotes}

    def send(
        self, coid: str, session: date, symbol: str, buy: bool, quantity: int, *, check: bool = True
    ) -> dict[str, Any]:
        if check:
            self.switch.require_clear()
        self.sent.append((coid, symbol, buy, quantity))
        price = self._quotes[symbol]["last_price"]
        self.held[symbol] = self.held.get(symbol, 0) + (quantity if buy else -quantity)
        self.views[coid] = {"status": "complete", "filled": quantity, "average_price": price}
        return {"event": "send_ok", "broker_order_id": f"B{len(self.sent)}", "detail": ""}

    def order(self, coid: str) -> dict[str, Any] | None:
        return self.views.get(coid)

    def positions(self) -> dict[str, int]:
        return {s: q for s, q in self.held.items() if q}

    def funds(self) -> float | None:
        return 1000.0


# --- sizing -----------------------------------------------------------------------------------


def test_small_amount_cuts_names_never_oversizes() -> None:
    one = lm.size(settings())
    assert (one.names, one.per_name, one.exposure) == (1, 5000.0, 5000.0)
    many = lm.size(settings(capital=100_000, leverage=1))
    assert many.names == 10 and many.per_name == 10_000
    assert lm.size(settings(capital=12_000, leverage=1)).names == 2


def test_too_small_is_refused_with_the_amount_needed() -> None:
    sized = lm.size(settings(capital=500, leverage=1))
    assert sized.names == 0 and "at least ₹5,000" in sized.refused


def test_leverage_is_capped_at_five() -> None:
    with pytest.raises(ValueError):
        settings(leverage=6)


# --- arming -----------------------------------------------------------------------------------


def test_deploy_needs_the_word_and_a_clear_switch(tmp_path: Path, switch: KillSwitch) -> None:
    at = datetime(2026, 11, 9, 14, 0, tzinfo=IST)
    assert lm.arm(settings(), "yes", at=at, root=tmp_path)["status"] == "refused"
    switch.trip("test")
    assert (
        "kill switch"
        in lm.arm(settings(), "DEPLOY", at=at, root=tmp_path, tripped=switch.is_tripped)["why"]
    )


def test_deploy_after_the_open_arms_the_next_session(tmp_path: Path, switch: KillSwitch) -> None:
    body = lm.arm(settings(), "DEPLOY", at=datetime(2026, 11, 9, 14, 0, tzinfo=IST), root=tmp_path)
    assert body["status"] == "armed" and body["for_session"] == "2026-11-10"
    early = lm.arm(settings(), "DEPLOY", at=datetime(2026, 11, 10, 8, 0, tzinfo=IST), root=tmp_path)
    assert early["for_session"] == "2026-11-10"
    friday = lm.arm(
        settings(), "DEPLOY", at=datetime(2026, 11, 13, 16, 0, tzinfo=IST), root=tmp_path
    )
    assert friday["for_session"] == "2026-11-16"


# --- picks ------------------------------------------------------------------------------------


PREV = {"UPCO": 100.0, "DOWNCO": 200.0, "FLAT": 300.0, "NEWS": 100.0, "WIDE": 100.0}
QUOTES = {
    "UPCO": quote(105.0, 104.9, 105.0),  # +5%: short
    "DOWNCO": quote(192.0, 191.9, 192.0),  # -4%: buy
    "FLAT": quote(301.0, 300.9, 301.0),
    "NEWS": quote(110.0, 109.9, 110.0),  # +10% but filed
    "WIDE": quote(106.0, 105.0, 107.0),  # spread ~190 bps
}


def test_pick_fades_the_gap_skips_news_and_wide_spreads() -> None:
    chosen = lm.pick(
        PREV, QUOTES, frozenset({"NEWS"}), lm.size(settings(capital=20_000, leverage=1))
    )
    picks = {p["symbol"]: p for p in chosen["picks"]}
    assert list(picks) == ["UPCO", "DOWNCO"]  # largest gap first
    assert picks["UPCO"]["side"] == -1 and picks["DOWNCO"]["side"] == 1
    assert picks["UPCO"]["quantity"] == int(5_000 / 104.9)  # 4 names of ₹5,000
    assert chosen["skipped"] == {"no quote": 0, "small gap": 1, "filing": 1, "spread": 1, "size": 0}


def test_one_name_takes_only_the_largest_gap() -> None:
    chosen = lm.pick(PREV, QUOTES, frozenset({"NEWS"}), lm.size(settings()))
    assert [p["symbol"] for p in chosen["picks"]] == ["UPCO"]


# --- the day ----------------------------------------------------------------------------------


def _armed(tmp_path: Path, **kw: Any) -> lm.Settings:
    s = settings(capital=20_000, leverage=1, **kw)
    lm.write(
        tmp_path / "deploy.json",
        {"status": "armed", "for_session": DAY.isoformat(), "settings": s.model_dump()},
    )
    lm.write(
        lm.day_dir(DAY, tmp_path) / "plan.json",
        {"status": "ok", "data_through": "2026-11-09", "prev_close": PREV},
    )
    return s


def no_news(_p: date, _s: date, _x: Any) -> frozenset[str]:
    return frozenset({"NEWS"})


def test_dry_run_sends_nothing(tmp_path: Path, switch: KillSwitch) -> None:
    _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)
    body = lm.enter(DAY, desk, send=False, root=tmp_path, filings=no_news)
    assert body["status"] == "dry run" and len(body["picks"]) == 2 and desk.sent == []


def test_entry_sends_against_the_gap_with_deterministic_ids(
    tmp_path: Path, switch: KillSwitch
) -> None:
    _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)
    lm.enter(DAY, desk, send=True, root=tmp_path, filings=no_news)
    assert [(s, b) for _, s, b, _ in desk.sent] == [("UPCO", False), ("DOWNCO", True)]
    assert desk.sent[0][0] == lm.client_order_id(DAY, "UPCO", 0)


def test_no_filings_list_means_no_trade(tmp_path: Path, switch: KillSwitch) -> None:
    _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)

    def down(*_a: Any) -> frozenset[str]:
        raise OSError("NSE refused")

    body = lm.enter(DAY, desk, send=True, root=tmp_path, filings=down)
    assert body["status"] == "no filings list" and desk.sent == []


def test_tripped_switch_blocks_entry(tmp_path: Path, switch: KillSwitch) -> None:
    _armed(tmp_path)
    switch.trip("drill")
    desk = FakeDesk(QUOTES, switch)
    body = lm.enter(DAY, desk, send=True, root=tmp_path, filings=no_news)
    assert desk.sent == [] and body["orders"][0]["event"] == "not sent"
    with pytest.raises(KillSwitchTripped):
        desk.send("x", DAY, "UPCO", True, 1)


def test_loss_cap_trips_the_switch_and_closes_everything(
    tmp_path: Path, switch: KillSwitch
) -> None:
    s = _armed(tmp_path, loss_cap=100.0)
    desk = FakeDesk(QUOTES, switch)
    lm.enter(DAY, desk, send=True, root=tmp_path, filings=no_news)
    desk._quotes["UPCO"] = quote(105.0, 107.9, 108.0)  # the short is down ~3%
    marked = lm.watch(DAY, desk, s, root=tmp_path)
    assert marked["net"] < -100 and switch.is_tripped()
    assert desk.positions() == {}  # exits go through with the switch tripped
    assert lm.read(lm.day_dir(DAY, tmp_path) / "close.json")["status"] == "flat"


def test_watch_under_the_cap_does_nothing(tmp_path: Path, switch: KillSwitch) -> None:
    s = _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)
    lm.enter(DAY, desk, send=True, root=tmp_path, filings=no_news)
    lm.watch(DAY, desk, s, root=tmp_path)
    assert not switch.is_tripped() and len(desk.positions()) == 2


def test_exit_is_idempotent(tmp_path: Path, switch: KillSwitch) -> None:
    _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)
    lm.enter(DAY, desk, send=True, root=tmp_path, filings=no_news)
    lm.exit_all(DAY, desk, "15:10", root=tmp_path)
    sent = len(desk.sent)
    lm.exit_all(DAY, desk, "15:10 again", root=tmp_path)
    assert len(desk.sent) == sent and desk.positions() == {}


def test_tick_runs_the_day_by_the_clock(
    tmp_path: Path, switch: KillSwitch, monkeypatch: pytest.MonkeyPatch
) -> None:
    _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)
    monkeypatch.setattr(lm, "filed_symbols", no_news)
    original = lm.enter

    def enter(*a: Any, **k: Any) -> dict[str, Any]:
        return original(*a, **{**k, "filings": no_news})

    monkeypatch.setattr(lm, "enter", enter)

    def run(h: int, m: int) -> str:
        at = datetime(2026, 11, 10, h, m, tzinfo=IST)
        return lm.tick(at, root=tmp_path, desk_factory=lambda: desk)

    assert run(9, 16) == "waiting for 09:20"
    assert run(9, 20) == "entered" and len(desk.sent) == 2
    assert run(9, 21) == "watched"
    assert run(15, 10) == "exited" and desk.positions() == {}
    assert run(15, 11) == "done"
    assert lm.read(tmp_path / "deploy.json")["status"] == "stopped"
    assert run(15, 12) == "idle"


def test_a_late_start_never_enters(tmp_path: Path, switch: KillSwitch) -> None:
    _armed(tmp_path)
    desk = FakeDesk(QUOTES, switch)
    out = lm.tick(
        datetime(2026, 11, 10, 10, 0, tzinfo=IST), root=tmp_path, desk_factory=lambda: desk
    )
    assert out == "missed" and desk.sent == []


def test_costs_match_angels_schedule() -> None:
    # ₹5,000 a side: ₹5 brokerage each way, STT on the sell, small fees, GST.
    cost = lm.round_trip_cost(500.0, 500.0, 10)
    assert 12.5 < cost < 14.5
