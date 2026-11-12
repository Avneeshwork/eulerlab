"""Angel One read-only check, quotes and the supervised proof (ADR-154). No network."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.broker import angel_check as angel
from eulerlab.broker.smartapi import SmartAPIBroker


def _full(token: str, ltp: float, bid: float, ask: float) -> dict[str, Any]:
    return {
        "tradingSymbol": "X-EQ",
        "symbolToken": token,
        "ltp": ltp,
        "open": ltp - 1,
        "close": ltp - 2,
        "exchFeedTime": "08-Nov-2026 09:16:01",
        "depth": {
            "buy": [{"price": bid, "quantity": 10, "orders": 1}],
            "sell": [{"price": ask, "quantity": 7, "orders": 1}],
        },
    }


class FakeClient:
    """The SmartConnect methods the module calls, with canned replies."""

    def __init__(self) -> None:
        self.searched: list[str] = []
        self.market_calls: list[list[str]] = []
        self.placed: list[dict[str, Any]] = []
        self.fill = "complete"

    def searchScrip(self, exchange: str, symbol: str) -> dict[str, Any]:
        self.searched.append(symbol)
        return {
            "status": True,
            "data": [
                {"tradingsymbol": f"{symbol}-BE", "symboltoken": "1"},
                {"tradingsymbol": f"{symbol}-EQ", "symboltoken": str(1000 + sum(map(ord, symbol)))},
            ],
        }

    def getMarketData(self, mode: str, tokens: dict[str, list[str]]) -> dict[str, Any]:
        ids = tokens["NSE"]
        self.market_calls.append(ids)
        return {"status": True, "data": {"fetched": [_full(t, 100.0, 99.9, 100.1) for t in ids]}}

    def getProfile(self, refresh: str) -> dict[str, Any]:
        return {"status": True, "data": {"name": "secret name"}}

    def rmsLimit(self) -> dict[str, Any]:
        return {"status": True, "data": {"availablecash": "5000.00"}}

    def orderBook(self) -> dict[str, Any]:
        rows = [
            {
                "orderid": f"B{i}",
                "ordertag": p["ordertag"],
                "orderstatus": self.fill,
                "filledshares": "1" if self.fill == "complete" else "0",
                "averageprice": "100.0",
            }
            for i, p in enumerate(self.placed)
        ]
        return {"status": True, "data": rows}

    def position(self) -> dict[str, Any]:
        return {"status": True, "data": None}

    def nseIntraday(self) -> dict[str, Any]:
        return {"status": True, "data": [{"SymbolName": "SBIN", "Multiplier": "5"}]}

    def placeOrderFullResponse(self, params: dict[str, Any]) -> dict[str, Any]:
        self.placed.append(params)
        return {"status": True, "data": {"orderid": f"B{len(self.placed) - 1}"}}


def test_quotes_map_to_the_kite_shape_and_batch(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(angel, "TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(angel, "QUOTE_BATCH", 2)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = FakeClient()
    found = angel.quotes(["SBIN", "INFY", "TCS"], client, master=None)
    assert set(found) == {"SBIN", "INFY", "TCS"}
    assert [len(x) for x in client.market_calls] == [2, 1]
    row = found["SBIN"]
    assert row["depth"]["buy"][0]["price"] == 99.9 and row["depth"]["sell"][0]["price"] == 100.1
    assert row["ohlc"]["open"] == 99.0 and row["source"] == "angel"


def test_tokens_are_cached_and_pick_the_eq_line(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    client = FakeClient()
    first = angel.tokens_for(client, ["SBIN"], pause=0, path=path, master=None)
    again = angel.tokens_for(client, ["SBIN"], pause=0, path=path, master=None)
    assert first == again == {"SBIN": str(1000 + sum(map(ord, "SBIN")))}
    assert client.searched == ["SBIN"]


MASTER = [
    {"token": "3045", "symbol": "SBIN-EQ", "exch_seg": "NSE"},
    {"token": "9", "symbol": "SBIN-BE", "exch_seg": "NSE"},
    {"token": "77", "symbol": "ODDCO-BE", "exch_seg": "NSE"},
    {"token": "500112", "symbol": "SBIN", "exch_seg": "BSE"},
    {"token": "99926000", "symbol": "Nifty 50", "exch_seg": "NSE"},
]


def test_master_tokens_take_the_eq_line_and_fall_back_to_be() -> None:
    assert angel.master_tokens(MASTER) == {"SBIN": "3045", "ODDCO": "77"}


def test_the_master_resolves_a_universe_without_searching(tmp_path: Path) -> None:
    """searchScrip is rate-limited after a handful of calls (2026-11-09), so a
    two-thousand-name universe must come from the master, read once a day."""
    path = tmp_path / "tokens.json"
    client = FakeClient()
    reads: list[int] = []

    def master() -> list[dict[str, Any]]:
        reads.append(1)
        return MASTER

    names = ["SBIN", "ODDCO", *[f"GONE{i}" for i in range(9)]]
    found = angel.tokens_for(client, names, pause=0, path=path, master=master)
    assert found["SBIN"] == "3045" and found["ODDCO"] == "77"
    assert client.searched == [
        f"GONE{i}" for i in range(angel.SEARCH_LIMIT)
    ]  # the rest are not searched
    angel.tokens_for(client, ["GONE8"], pause=0, path=path, master=master)
    assert reads == [1]  # fresh for a day: not downloaded again


def test_an_unrecognised_quote_reply_is_refused() -> None:
    with pytest.raises(angel.AngelError, match="not recognised"):
        angel.parse_quotes({"status": True, "data": {"rows": []}}, {})
    with pytest.raises(angel.AngelError, match="refused"):
        angel.parse_quotes({"status": False, "message": "bad token"}, {})


def test_readonly_reads_everything_and_writes_no_secret(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(angel, "TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(time, "sleep", lambda _: None)
    # The scrip master is a 38 MB public download; a test must not reach the
    # internet (it failed behind a proxy on 2026-11-12). A fresh token cache
    # means the master is not consulted.
    angel._save_tokens(
        {"SBIN": "3045"}, tmp_path / "tokens.json", master_at=datetime.now(UTC).isoformat()
    )
    client = FakeClient()
    out = tmp_path / "ro.json"
    report = angel.readonly(client, "refresh-token-value", "SBIN", out)
    assert report["funds_available"] == "5000.00"
    assert report["open_orders"] == 0 and report["positions"] == 0
    assert report["quote"]["last_price"] == 100.0
    assert report["nse_intraday_list"]["count"] == 1
    written = out.read_text(encoding="utf-8")
    assert "refresh-token-value" not in written and "secret name" not in written
    assert client.placed == []


IST_1000 = datetime(2026, 11, 9, 4, 30, tzinfo=UTC)  # Monday 10:00 IST


def test_refusals() -> None:
    ist = IST_1000 + angel.IST
    assert "CONFIRM=SEND" in angel.refuse("", ist, False)
    assert "kill switch" in angel.refuse("SEND", ist, True)
    assert angel.refuse("SEND", ist.replace(hour=9, minute=16), False).startswith("only")
    assert angel.refuse("SEND", ist.replace(day=8), False) == "not a weekday"
    assert angel.refuse("SEND", ist, False) == ""


def _proof(tmp_path: Path, client: FakeClient, confirm: str = "SEND", **kw: Any) -> Any:
    return angel.proof(
        "SBIN",
        confirm,
        now=lambda: IST_1000,
        path=tmp_path / "proof.json",
        tripped=kw.pop("tripped", lambda: False),
        connect=lambda: (client, "r"),
        make_broker=lambda c, t: SmartAPIBroker(c, symbol_tokens=t),
        timeout=kw.pop("timeout", 1.0),
    )


def test_proof_without_confirm_sends_nothing(tmp_path: Path) -> None:
    client = FakeClient()
    body = _proof(tmp_path, client, confirm="")
    assert body["status"] == "refused" and client.placed == []
    body = _proof(tmp_path, client, tripped=lambda: True)
    assert body["status"] == "refused" and client.placed == []


def test_proof_round_trip_writes_the_proof(tmp_path: Path) -> None:
    client = FakeClient()
    body = _proof(tmp_path, client)
    assert body["status"] == "ok"
    assert [p["transactiontype"] for p in client.placed] == ["BUY", "SELL"]
    assert all(p["producttype"] == "INTRADAY" and p["quantity"] == "1" for p in client.placed)
    assert all(p["symboltoken"] == str(1000 + sum(map(ord, "SBIN"))) for p in client.placed)
    saved = json.loads((tmp_path / "proof.json").read_text(encoding="utf-8"))
    assert saved["broker"] == "angel" and len(saved["legs"]) == 2
    # deterministic ids: the same moment gives the same tags, so a retry cannot double-send
    again = FakeClient()
    _proof(tmp_path, again)
    assert [p["ordertag"] for p in again.placed] == [p["ordertag"] for p in client.placed]


def test_an_unfilled_buy_stops_before_the_sell(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = FakeClient()
    client.fill = "rejected"
    body = _proof(tmp_path, client)
    assert body["status"].startswith("incomplete") and len(client.placed) == 1
    assert not (tmp_path / "proof.json").exists()
