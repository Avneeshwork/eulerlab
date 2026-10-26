"""The bot's wider words, and how a message is read (ADR-068).

Operator, 2026-10-12: "build telegram bot more generalized and more features
make it broad". Broad, and still unable to trade: the tests below fix both.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from eulerlab import notify, telegram_words
from eulerlab import telegram_bot as bot

# --- how a message is read ------------------------------------------------------------


def test_a_word_can_be_shortened() -> None:
    assert bot.resolve("positions") == "positions"
    assert bot.resolve("pos") == "positions"
    assert bot.resolve("p") == "positions"
    assert bot.resolve("mov") == "movers", "a start only one word has"
    assert bot.resolve("s") == "status", "a listed short form wins over an unclear start"
    assert bot.resolve("st") == "status"
    assert bot.resolve("zzz") is None


def test_no_short_form_means_two_words() -> None:
    seen: dict[str, str] = {}
    for name, command in bot.COMMANDS.items():
        for short in command.short:
            assert short not in bot.COMMANDS, f"'{short}' is also a word"
            assert seen.setdefault(short, name) == name, f"'{short}' is short for two words"


def test_a_near_miss_is_offered_back_and_not_sent_to_a_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_: str) -> str:
        raise AssertionError("a mistyped word went to the assistant")

    monkeypatch.setattr(telegram_words, "ask", forbidden)
    monkeypatch.setitem(bot.COMMANDS, "ask", bot.Command("x", forbidden, "Assistant"))
    assert bot.answer("positons 2 please now") == (
        "I do not know 'positons'. Did you mean `positions`?"
    )
    assert bot.answer("sell everything").startswith("I do not know 'sell'.")
    assert bot.answer("/unknown thing with words").startswith("I do not know '/unknown'.")


def test_a_sentence_goes_to_the_assistant_unless_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(bot.COMMANDS, "ask", bot.Command("x", lambda q: f"asked: {q}", "Assistant"))
    assert bot.answer("which deployment did best") == "asked: which deployment did best"
    assert bot.answer("why down?") == "asked: why down?"
    monkeypatch.setenv(telegram_words.ASK_ENV, "0")
    assert bot.answer("which deployment did best").startswith("I do not know 'which'.")


def test_help_is_grouped_and_explains_one_word() -> None:
    whole = bot.help_text()
    for group in ("Deployments", "Market", "Research", "Machine", "Assistant"):
        assert f"\n{group}\n" in whole
    one = bot.answer("help pos")
    assert one.startswith("positions — ")
    assert "Send: positions 2, or positions nifty" in one and "Short: pos, p" in one


def test_every_word_fits_telegrams_menu() -> None:
    """Telegram accepts 1 to 32 of a-z, 0-9 and underscore, and 100 commands."""
    assert len(bot.COMMANDS) <= 100
    for word, command in bot.COMMANDS.items():
        assert word.isascii() and word.replace("_", "").isalnum() and word == word.lower()
        assert 1 <= len(word) <= 32 and 1 <= len(command.what) <= 256


def test_a_long_answer_is_split_between_lines_and_nothing_is_lost() -> None:
    lines = [f"row {i} " + "x" * 40 for i in range(300)]
    pieces = list(bot.chunks("\n".join(lines), limit=1000))
    assert len(pieces) > 1 and all(len(p) <= 1000 for p in pieces)
    assert "\n".join(pieces).splitlines() == lines
    assert list(bot.chunks("y" * 2500, limit=1000)) == ["y" * 1000, "y" * 1000, "y" * 500]
    assert list(bot.chunks("short")) == ["short"]


def test_a_reply_goes_only_to_the_operators_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    def call(method: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
        sent.append((method, dict(params)))
        return {"ok": True}

    monkeypatch.setattr(notify, "_env", lambda name: "4242" if name == notify.CHAT_ENV else "tok")
    monkeypatch.setattr(bot, "_call", call)
    assert bot.reply("a\n" + "b" * 5000) is True
    assert [m for m, _ in sent] == ["sendMessage"] * 3
    assert {p["chat_id"] for _, p in sent} == {"4242"}
    assert "status" in json.loads(sent[0][1]["reply_markup"])["keyboard"][0]


def test_every_button_is_a_word() -> None:
    for row in bot.KEYBOARD:
        for word in row:
            assert word in bot.COMMANDS


# --- a deployment by name ---------------------------------------------------------------


def _two_deployments(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.deploy import deployments as store

    first = SimpleNamespace(
        id="paper-india_sharpe_momentum_opt-1",
        strategy_id="india_sharpe_momentum_opt",
        mode="paper",
        capital=100000.0,
        status="active",
    )
    second = SimpleNamespace(
        id="paper-nifty_calm_rise_overnight-2",
        strategy_id="nifty_calm_rise_overnight",
        mode="paper",
        capital=2000000.0,
        status="active",
    )
    states = {
        first.id: {
            "equity": 102000.0,
            "curve": [["2026-10-08", 100000.0], ["2026-10-09", 102000.0]],
            "book": [{"symbol": "CUPID", "quantity": 35, "value": 12813.5, "weight": 0.12}],
        },
        second.id: {"equity": 1999000.0, "curve": [["2026-10-09", 1999000.0]], "book": []},
    }
    monkeypatch.setattr(store, "all_deployments", lambda: [first, second])
    monkeypatch.setattr(store, "read_state", lambda d: states[d.id])


def test_a_deployment_is_picked_by_part_of_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _two_deployments(monkeypatch)
    assert bot.answer("positions momentum").startswith("paper-india_sharpe_momentum_opt-1")
    assert bot.answer("pos overnight") == "paper-nifty_calm_rise_overnight-2 holds nothing."
    assert "fits 2 deployments" in bot.answer("positions paper")
    assert "is not a number or part of a deployment's name" in bot.answer("positions zzz")
    assert "There is no deployment 3" in bot.answer("p 3")


def test_pnl_gives_each_deployment_and_the_total(monkeypatch: pytest.MonkeyPatch) -> None:
    _two_deployments(monkeypatch)
    text = bot.answer("pnl")
    assert "₹+2,000 (+2.00%) · 2026-10-09: +2.00%" in text
    assert "₹-1,000 (-0.05%)" in text
    assert text.endswith("PAPER in all: ₹2,101,000 from ₹2,100,000 put in, ₹+1,000 (+0.05%)")


# --- the market and one stock -----------------------------------------------------------

SNAP: dict[str, Any] = {
    "ok": True,
    "as_of": "2026-10-09",
    "freshness": {"live": False, "taken_at": "", "reason": "no Kite session"},
    "regime": {
        "advancers": 1405,
        "decliners": 1370,
        "unchanged": 131,
        "proxy_return_20d": 0.021,
        "volatility": 0.142,
        "volatility_before": 0.12,
        "volatility_rising": True,
    },
    "movers": {
        "gainers": [{"symbol": "AAA", "return": 0.081, "relative_volume": 3.2}],
        "losers": [{"symbol": "BBB", "return": -0.052, "relative_volume": 1.0}],
        "unusual_volume": [{"symbol": "AAA", "return": 0.081, "relative_volume": 3.2}],
    },
}


def test_market_and_movers_say_whether_they_are_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_words, "_snapshot", lambda: SNAP)
    market = bot.answer("market")
    assert market.startswith("MARKET · NSE · close of 2026-10-09, not live (no Kite session)")
    assert "Up 1,405 · Down 1,370 · Flat 131" in market
    assert "Volatility 14.2% a year, rising from 12.0%" in market
    movers = bot.answer("movers")
    assert "Up\n  AAA +8.1%\nDown\n  BBB -5.2%" in movers
    assert movers.endswith("Unusual turnover on 2026-10-09\n  AAA 3.2x usual")
    monkeypatch.setattr(telegram_words, "_snapshot", lambda: {"ok": False, "error": "no panel"})
    assert bot.answer("market") == "No market view: no panel"


def _names(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "names.json"
    path.write_text(
        json.dumps(
            {"TCS": "Tata Consultancy Services", "TATASTEEL": "Tata Steel", "INFY": "Infosys"}
        )
    )
    monkeypatch.setattr(telegram_words, "NAMES_PATH", path)


def test_a_stock_is_found_by_symbol_or_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _names(monkeypatch, tmp_path)
    assert telegram_words._symbol("infy", "price") == ("INFY", "")
    assert telegram_words._symbol("infosys", "price") == ("INFY", "")
    symbol, say = telegram_words._symbol("tata", "price")
    assert symbol == "" and "matches 2 names" in say and "TATASTEEL: Tata Steel" in say
    assert telegram_words._symbol("", "price") == ("", "Which stock? For example: price RELIANCE")
    assert telegram_words._symbol("NEWCO", "price") == ("NEWCO", ""), "the data decides"


def test_price_gives_the_settled_close_when_no_quote_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from eulerlab import quotes
    from eulerlab.assistant import tools

    _names(monkeypatch, tmp_path)
    rows = [{"d": f"2026-09-{i + 1:02d}", "c": 100.0 + i} for i in range(25)]
    monkeypatch.setattr(tools, "_panel_rows", lambda symbol, days: rows)
    monkeypatch.setattr(quotes, "live", lambda symbols: quotes.QuoteResult())
    text = bot.answer("price infy")
    assert text.splitlines()[0] == "INFY · Infosys"
    assert "Last settled close 124.00 on 2026-09-25" in text
    assert "20 sessions: +19.2%" in text
    assert "low 100.00, high 124.00" in text and "Now" not in text

    quote = quotes.Quote("INFY", 126.0, 124.0, "zerodha", "2026-10-12T09:22:00+00:00")
    monkeypatch.setattr(quotes, "live", lambda symbols: quotes.QuoteResult({"INFY": quote}))
    assert "Now 126.00 (+1.61% on 124.00) · zerodha" in bot.answer("px INFY")

    monkeypatch.setattr(tools, "_panel_rows", lambda symbol, days: [])
    assert bot.answer("price INFY") == "No daily prices are held for INFY."


# --- the machine ------------------------------------------------------------------------


def test_kite_never_sends_the_login_link_or_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.api import kite_routes

    state = {
        "configured": True,
        "fresh": False,
        "reason": "no Kite token minted today",
        "login_url": "https://kite.zerodha.com/connect/login?api_key=SECRETKEY",
    }
    monkeypatch.setattr(kite_routes, "kite_status", lambda: state)
    text = bot.answer("kite")
    assert text.startswith("Kite: no Kite token minted today.")
    assert "SECRETKEY" not in text and "http" not in text
    monkeypatch.setattr(
        kite_routes,
        "kite_status",
        lambda: {**state, "fresh": True, "expires_at": "2026-10-13T00:30:00+00:00"},
    )
    assert "SECRETKEY" not in bot.answer("kite") and "logged in" in bot.answer("kite")


def test_kill_reports_the_switch_and_cannot_move_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from eulerlab.oms import killswitch

    trip = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(killswitch, "TRIP_PATH", trip)
    monkeypatch.setattr(
        killswitch,
        "KillSwitch",
        lambda: SimpleNamespace(
            is_tripped=trip.exists,
            reason=lambda: "daily loss",
        ),
    )
    assert bot.answer("kill").startswith("Kill switch: clear")
    assert not trip.exists(), "asking must not trip it"
    trip.write_text("{}")
    tripped = bot.answer("kill")
    assert tripped.startswith("KILL SWITCH: TRIPPED\nReason: daily loss")
    assert trip.exists(), "asking must not clear it"
    source = inspect.getsource(telegram_words.kill)
    assert ".trip(" not in source and "reset" not in source


def test_jobs_reads_the_last_exit_of_each(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    import subprocess

    listing = (
        "PID\tStatus\tLabel\n"
        "-\t2\tcom.eulerlab.daily\n"
        "-\t0\tcom.eulerlab.gapsignal\n"
        "812\t0\tcom.eulerlab.other\n"
        "-\t0\tcom.apple.thing\n"
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/launchctl")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=listing, returncode=0)
    )
    assert bot.answer("jobs") == (
        "SCHEDULED JOBS\n"
        "daily: last run FAILED (exit 2)\n"
        "gapsignal: last run finished cleanly\n"
        "other: running now"
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert "does not have" in bot.answer("jobs")


def test_brief_survives_a_part_that_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: str = "") -> str:
        raise RuntimeError("no panel")

    for name in ("pnl", "kite", "kill", "jobs"):
        monkeypatch.setattr(telegram_words, name, lambda _="", name=name: f"{name} fine")
    monkeypatch.setattr(telegram_words, "market", broken)
    monkeypatch.setattr(bot, "data", lambda _="": "Data: 9 ok")
    text = bot.answer("brief")
    assert "DEPLOYMENTS\npnl fine" in text and "DATA\nData: 9 ok" in text
    assert "broken failed: RuntimeError: no panel" in text
    assert text.endswith("jobs fine")


# --- the assistant ----------------------------------------------------------------------


def test_ask_keeps_the_thread_and_forget_drops_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.assistant import chat

    asked: list[list[dict[str, Any]]] = []

    def fake(messages: list[dict[str, Any]], **_: Any) -> chat.Answer:
        asked.append(list(messages))
        return chat.Answer(
            f"answer {len(asked)}",
            "openrouter-private",
            "a-model",
            "openrouter.ai",
            [{"name": "deployments"}, {"name": "deployments"}],
        )

    monkeypatch.setattr(chat, "ask", fake)
    telegram_words._turns.clear()
    first = bot.answer("ask which did best?")
    assert first == "answer 1\n\na-model via openrouter.ai · looked at: deployments"
    bot.answer("ask and the worst?")
    assert [m["content"] for m in asked[1]] == ["which did best?", "answer 1", "and the worst?"]
    assert bot.answer("forget").startswith("Forgotten")
    bot.answer("ask again?")
    assert [m["content"] for m in asked[2]] == ["again?"]
    telegram_words._turns.clear()


def test_a_refusal_is_said_plainly_and_not_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.assistant import chat

    def refuse(messages: list[dict[str, Any]], **_: Any) -> chat.Answer:
        raise chat.Refused("openrouter.ai is not reachable")

    monkeypatch.setattr(chat, "ask", refuse)
    telegram_words._turns.clear()
    assert bot.answer("ask anything?") == (
        "The assistant could not answer: openrouter.ai is not reachable"
    )
    assert not telegram_words._turns
