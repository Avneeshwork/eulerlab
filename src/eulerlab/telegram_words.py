"""The bot's wider answers: the market, one stock, results, and the machine itself.

Operator, 2026-10-12: "build telegram bot more generalized and more features
make it broad". `telegram_bot.py` holds the words about deployments and the
listener; this holds the rest, so that file stays about talking to Telegram.

Every function here takes the text after the word and returns the reply. Each
reads; none writes, places an order, or changes a setting (ADR-068).

### What is never sent

`kite` says whether today's token is valid. It does not send the login link,
which carries the API key: the phone is not where a login is done, and no
route in this project returns the key, the secret or the token.

### Plain sentences

`ask` passes a question to the assistant (ADR-064), under its rules: approved
hosts only, every request scrubbed of `.env` values, read-only tools. The bot
keeps the last few turns in memory so a follow-up makes sense; `forget` drops
them, and so does a restart.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.paths import data_path

IST = ZoneInfo("Asia/Kolkata")
NAMES_PATH = data_path("derived/nse_names.json")
ASK_ENV = "EULERLAB_TELEGRAM_ASK"
JOB_PREFIX = "com.eulerlab."
TOP = 5
YEAR = 252
CRORE = 1e7

_turns: deque[dict[str, str]] = deque(maxlen=8)
"""The conversation with the assistant so far: four questions and answers."""


def _names() -> dict[str, str]:
    if not NAMES_PATH.exists():
        return {}
    loaded: dict[str, str] = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    return loaded


def _pct(value: object, places: int = 1) -> str:
    return f"{float(value):+.{places}%}" if isinstance(value, int | float) else "—"


def _num(value: object, places: int = 2) -> str:
    return f"{float(value):,.{places}f}" if isinstance(value, int | float) else "—"


def _clock(stamp: str) -> str:
    """An ISO time as India's clock, with the day when it is not today."""
    try:
        when = datetime.fromisoformat(stamp).astimezone(IST)
    except ValueError:
        return stamp
    if when.date() == datetime.now(IST).date():
        return when.strftime("%H:%M")
    return when.strftime("%d %b %H:%M")


def _symbol(arg: str, word: str) -> tuple[str, str]:
    """(symbol, "") from what was typed, or ("", what to say instead)."""
    wanted = arg.strip().upper()
    if not wanted:
        return "", f"Which stock? For example: {word} RELIANCE"
    names = _names()
    if not names or wanted in names:
        return wanted, ""
    matches = [s for s, name in names.items() if wanted in s or wanted in name.upper()]
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        # Not every traded name is in the names file. Let the data decide.
        return wanted, ""
    matches.sort(key=lambda s: (not s.startswith(wanted), s))
    listed = "\n".join(f"{s}: {names[s]}" for s in matches[:12])
    return "", f"'{arg.strip()}' matches {len(matches)} names. Send one symbol:\n{listed}"


# --- the market ---------------------------------------------------------------------


def _snapshot() -> dict[str, Any]:
    from eulerlab.api import server

    return server.snapshot(live=True)


def _as_of(snap: dict[str, Any]) -> str:
    fresh = snap.get("freshness") or {}
    if fresh.get("live"):
        return f"live {_clock(str(fresh.get('taken_at') or ''))}"
    return f"close of {snap.get('as_of')}, not live ({fresh.get('reason') or 'no quote'})"


def market(_: str = "") -> str:
    snap = _snapshot()
    if not snap.get("ok"):
        return f"No market view: {snap.get('error')}"
    regime = snap["regime"]
    before = regime.get("volatility_before")
    trend = ""
    if isinstance(before, int | float):
        trend = f", {'rising' if regime.get('volatility_rising') else 'easing'} from {before:.1%}"
    return (
        f"MARKET · NSE · {_as_of(snap)}\n"
        f"Up {regime['advancers']:,} · Down {regime['decliners']:,} · "
        f"Flat {regime['unchanged']:,}\n"
        f"Average stock over 20 sessions: {_pct(regime['proxy_return_20d'])}\n"
        f"Volatility {regime['volatility']:.1%} a year{trend}\n"
        "Equal-weighted across every stock held, not an index."
    )


def movers(_: str = "") -> str:
    snap = _snapshot()
    if not snap.get("ok"):
        return f"No movers: {snap.get('error')}"
    found = snap["movers"]

    def rows(tiles: list[dict[str, Any]]) -> str:
        return "\n".join(f"  {t['symbol']} {_pct(t['return'])}" for t in tiles[:TOP]) or "  none"

    # Turnover is the last settled day's, set against the twenty before it. It
    # is named with its date so it is not read as today's.
    unusual = "\n".join(
        f"  {t['symbol']} {t['relative_volume']}x usual" for t in found["unusual_volume"][:TOP]
    )
    return (
        f"MOVERS · {_as_of(snap)}\nUp\n{rows(found['gainers'])}\nDown\n{rows(found['losers'])}"
        + (f"\nUnusual turnover on {snap.get('as_of')}\n{unusual}" if unusual else "")
    )


# --- one stock ----------------------------------------------------------------------


def price(arg: str = "") -> str:
    from eulerlab import quotes
    from eulerlab.assistant import tools

    symbol, say = _symbol(arg, "price")
    if say:
        return say
    rows = tools._panel_rows(symbol, YEAR)
    if rows is None:
        return "The price panel has not been built."
    if not rows:
        return f"No daily prices are held for {symbol}."
    year = rows[-YEAR:]
    closes = [float(r["c"]) for r in year]
    lines = [f"{symbol} · {_names().get(symbol, '')}".rstrip(" ·")]
    try:
        quote = quotes.live([symbol]).quotes.get(symbol)
    except Exception:  # a quote is extra; the settled answer still stands
        quote = None
    if quote is not None:
        change = f" ({quote.change_pct:+.2f}% on {_num(quote.previous_close)})"
        lines.append(
            f"Now {_num(quote.last)}{change if quote.previous_close else ''} · "
            f"{quote.source} {_clock(quote.at)}"
        )
    lines.append(f"Last settled close {_num(closes[-1])} on {year[-1]['d']}")
    month = closes[-21:]
    if len(month) > 1:
        lines.append(f"{len(month) - 1} sessions: {_pct(month[-1] / month[0] - 1)}")
    lines.append(
        f"{len(year)} sessions: low {_num(min(closes))}, high {_num(max(closes))} "
        "(closes as printed, not adjusted for splits)"
    )
    return "\n".join(lines)


def company(arg: str = "") -> str:
    from eulerlab.features import company as digest
    from eulerlab.features import company_page

    symbol, say = _symbol(arg, "company")
    if say:
        return say
    relative = company_page.latest_file(symbol)
    if relative is None:
        return f"No fundamentals are held for {symbol}."
    names = _names()
    page = company_page.build(
        symbol,
        company_page.read_columns(relative),
        companies=digest.load_digest(),
        names=names,
        as_of=Path(relative).stem,
    )
    profile, figures, peers = page["profile"], page["metrics"], page["peers"]
    cap = profile.get("market_cap")
    lines = [
        f"{page['name'] or symbol} ({symbol})",
        " > ".join(profile.get("sector_levels") or []) or "sector not held",
        f"Market cap ₹{float(cap) / CRORE:,.0f} crore" if cap else "Market cap not held",
        f"P/E {_num(profile.get('pe'), 1)} · ROCE {_num(profile.get('roce'), 1)}% · "
        f"ROE {_num(profile.get('roe'), 1)}%",
        f"Year to {figures.get('annual_period') or '—'}: sales {_pct(figures.get('sales_growth'))}, "
        f"profit {_pct(figures.get('profit_growth'))}, net margin "
        f"{_pct(figures.get('net_margin')).lstrip('+')}",
        f"Quarter {figures.get('quarter_period') or '—'} on a year before: sales "
        f"{_pct(figures.get('quarter_sales_growth'))}, profit "
        f"{_pct(figures.get('quarter_profit_growth'))}",
        f"Debt to equity {_num(figures.get('debt_to_equity'))} · promoters hold "
        f"{_num(figures.get('promoter_holding'), 1)}%",
    ]
    if peers.get("median_pe") is not None:
        lines.append(
            f"{peers['industry']}: median P/E {_num(peers['median_pe'], 1)} "
            f"across {peers['pe_count']} companies"
        )
    lines.append(f"From screener.in, file of {page['as_of']}. No analyst data is held.")
    return "\n".join(lines)


def news(arg: str = "") -> str:
    from eulerlab.features import company_page

    symbol, say = _symbol(arg, "news")
    if say:
        return say
    found = company_page.news(symbol, company_page.news_files(), _names().get(symbol, ""))
    if not found:
        return f"No held headline names {symbol}."
    return f"NEWS · {symbol}\n" + "\n\n".join(
        f"{row['time'][:10]} · {row['publisher']}\n{row['title']}\n{row['link']}"
        for row in found[:TOP]
    )


# --- research -----------------------------------------------------------------------


def _run_line(run: Any) -> str:
    return (
        f"Sharpe {run.sharpe:.2f} · return {_pct(run.total_return)} · "
        f"worst fall {_pct(-abs(run.max_drawdown))} · {run.days:,} days · {run.fills:,} fills"
    )


def results(arg: str = "") -> str:
    from eulerlab import results as store
    from eulerlab import workspace as workspace_mod
    from eulerlab.assistant import tools
    from eulerlab.strategies import REGISTRY

    wanted = arg.strip()
    if not wanted:
        return "Which strategy? Send `results <id>`, or `strategies <word>` to find the id."
    if wanted not in REGISTRY:
        found = [d for d in REGISTRY.values() if wanted.lower() in f"{d.id} {d.title}".lower()]
        if len(found) != 1:
            return tools._strategies({"search": wanted})
        wanted = found[0].id
    workspace = workspace_mod.resolve(None)
    runs = store.distinct(workspace, wanted)
    latest = store.latest(workspace, wanted, runs)
    if latest is None:
        return f"{REGISTRY[wanted].title}\nNo run of this strategy is stored."
    lines = [REGISTRY[wanted].title, f"Latest run: {_run_line(latest)}"]
    best = store.best(workspace, wanted, runs)
    if best is not None and best.is_a_maximum:
        lines.append(
            f"Best of {best.runs} configurations: {_run_line(best.run)}\n"
            "That is the winner of a search, not a measurement."
        )
    return "\n".join(lines)


def trials(_: str = "") -> str:
    from eulerlab.validation import ledger

    chain = ledger.verify_chain()
    state = "intact" if chain.intact else f"BROKEN at entry {chain.broken_at}: {chain.detail}"
    return f"{ledger.count():,} strategy configurations tried so far.\nThe trial log is {state}."


# --- money --------------------------------------------------------------------------


def pnl(_: str = "") -> str:
    from eulerlab import telegram_bot
    from eulerlab.deploy import deployments as store
    from eulerlab.deploy.signals import title_of
    from eulerlab.risk import book as rb

    found = telegram_bot._deployments()
    if not found:
        return "No active deployments."
    lines: list[str] = []
    totals: dict[str, list[rb.Book]] = {}
    for number, deployment in enumerate(found, start=1):
        state = store.read_state(deployment) or {}
        equity = state.get("equity")
        if not isinstance(equity, int | float):
            lines.append(f"{number}. {title_of(deployment.strategy_id)}: not run yet")
            continue
        # Deposits and withdrawals are not profit: the gain is equity less the
        # money put in, the percentage time-weighted (`risk.book.growth`).
        book = rb.book_from_state(
            deployment.id, deployment.strategy_id, "", deployment.capital, "", state
        )
        path = book.growth()
        day = ""
        if len(path) > 1 and path[-2][1]:
            day = f" · {path[-1][0]}: {_pct(path[-1][1] / path[-2][1] - 1, 2)}"
        lines.append(
            f"{number}. {title_of(deployment.strategy_id)}\n"
            f"   ₹{book.made:+,.0f} ({_pct(book.total_return, 2)}){day}"
        )
        totals.setdefault(deployment.mode.upper(), []).append(book)
    for mode, books in sorted(totals.items()):
        deployed = sum(b.deployed for b in books)
        equity = sum(b.equity for b in books)
        # The same whole-book return as the risk page (`risk.report.build`).
        path = rb.growth(
            rb.combined_curve(books),
            [flow for b in books for flow in b.flows],
            sum(b.capital for b in books),
        )
        lines.append(
            f"{mode} in all: ₹{equity:,.0f} from ₹{deployed:,.0f} put in, "
            f"₹{equity - deployed:+,.0f} ({_pct(path[-1][1] - 1 if path else 0.0, 2)})"
        )
    return "\n".join(lines)


# --- the machine --------------------------------------------------------------------


def jobs(_: str = "") -> str:
    if shutil.which("launchctl") is None:
        return "Scheduled jobs are run by launchd, which this machine does not have."
    listed = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True, timeout=10, check=False
    )
    lines = []
    for row in listed.stdout.splitlines():
        parts = row.split()
        if len(parts) != 3 or not parts[2].startswith(JOB_PREFIX):
            continue
        pid, code, label = parts
        name = label.removeprefix(JOB_PREFIX)
        if pid != "-":
            lines.append(f"{name}: running now")
        elif code == "0":
            lines.append(f"{name}: last run finished cleanly")
        else:
            lines.append(f"{name}: last run FAILED (exit {code})")
    if not lines:
        return "No scheduled job is installed. `make schedule` installs the nightly one."
    return "SCHEDULED JOBS\n" + "\n".join(sorted(lines))


def kite(_: str = "") -> str:
    from eulerlab.api import kite_routes

    state = kite_routes.kite_status()
    if state.get("fresh"):
        return f"Kite: logged in. The token lasts until {_clock(str(state['expires_at']))}."
    return (
        f"Kite: {state.get('reason')}.\n"
        "Log in on the machine: Tools → Instruments → Kite. Live prices and the "
        "pre-close signal need it."
    )


def kill(_: str = "") -> str:
    from eulerlab.oms import killswitch

    switch = killswitch.KillSwitch()
    if switch.is_tripped():
        return (
            f"KILL SWITCH: TRIPPED\nReason: {switch.reason() or 'not recorded'}\n"
            "No order is sent while it is tripped. It is cleared on the machine, not here."
        )
    limits = killswitch.load_limits()
    return (
        "Kill switch: clear\n"
        f"Daily loss limit ₹{limits.max_daily_loss:,.0f} · {limits.max_orders_per_day} orders "
        f"a day · position ₹{limits.max_position_notional:,.0f}\n"
        "This bot can neither trip nor clear it: `make kill-stop` on the machine."
    )


# --- everything at once ---------------------------------------------------------------


def brief(_: str = "") -> str:
    """The words a morning or evening check needs, in one message."""
    from eulerlab import telegram_bot

    parts = (
        ("DEPLOYMENTS", pnl),
        ("", market),
        ("DATA", telegram_bot.data),
        ("", kite),
        ("", kill),
        ("", jobs),
    )
    out = []
    for heading, handler in parts:
        try:
            body = handler("")
        except Exception as exc:  # one broken part must not cost the other five
            body = f"{handler.__name__} failed: {type(exc).__name__}: {str(exc)[:120]}"
        out.append(f"{heading}\n{body}" if heading else body)
    return "\n\n".join(out)


# --- the agent network (ADR-085) ------------------------------------------------------
#
# `instruct` is the one word that writes anything: it saves a brief, which steers what
# an agent looks at and nothing else (agents/briefs.py). It cannot start a run,
# change a budget, approve an item or trade.


def agents(_: str = "") -> str:
    from eulerlab.agents import inbox, log, runtime
    from eulerlab.agents.spec import all_effective

    lines = []
    for name, agent in sorted(all_effective().items()):
        latest = runtime.latest_output(name, status=None)
        state = "on" if agent.enabled else "off"
        last = (
            f"{latest.status} {latest.started[5:16].replace('T', ' ')}" if latest else "never run"
        )
        lines.append(f"{name} ({state}): {last}")
    ok, problem = log.verify()
    waiting = len(inbox.pending())
    return (
        "AGENTS\n"
        + "\n".join(lines)
        + f"\n\nInbox: {waiting} waiting for you"
        + ("" if ok else f"\nAGENT LOG BROKEN: {problem}")
    )


def instruct(arg: str = "") -> str:
    from eulerlab.agents import briefs
    from eulerlab.agents.spec import load_specs

    parts = arg.strip().split(maxsplit=1)
    names = sorted(load_specs())
    if len(parts) < 2:
        return "instruct <agent or all> <what to focus on>. Agents: " + ", ".join(names)
    who, text = parts[0].lower(), parts[1]
    if who != briefs.ALL and who not in names:
        return f"No agent '{who}'. Agents: {', '.join(names)}, or all."
    saved = briefs.write(who, text, by="telegram")
    return f"Brief saved for {who} ({saved.id}). Its next run reads it. A brief steers; it cannot change limits."


def feedback(arg: str = "") -> str:
    """The feedback desk (ADR-152): a rule becomes a lesson, anything else a head's task."""
    from eulerlab.agents import feedback as desk

    if not arg.strip():
        return "feedback <what you want>. A rule (never, always, avoid...) becomes a lesson; the rest goes to a head."
    return desk.say(desk.route(arg, by="telegram"))


def outlook(_: str = "") -> str:
    from eulerlab.agents import runtime

    latest = runtime.latest_output("market_brief")
    if latest is None:
        return "No market brief yet. It runs at 08:45 and after the close."
    return str(latest.data.get("text") or latest.summary)


def inbox_word(_: str = "") -> str:
    from eulerlab.agents import inbox

    waiting = inbox.pending()
    if not waiting:
        return "Nothing is waiting for you."
    lines = [f"- {row['agent']}: {row['title']}" for row in waiting[:12]]
    more = f"\n…and {len(waiting) - 12} more" if len(waiting) > 12 else ""
    return (
        f"INBOX · {len(waiting)} waiting\n"
        + "\n".join(lines)
        + more
        + "\nDecide on the AI page of the workbench."
    )


# --- plain sentences ------------------------------------------------------------------


def ask_enabled() -> bool:
    return os.environ.get(ASK_ENV, "1") != "0"


def ask(arg: str = "") -> str:
    from eulerlab.assistant import chat
    from eulerlab.llm import client

    question = arg.strip()
    if not question:
        return "Ask a question in plain words, for example: ask which deployment did best?"
    if not ask_enabled():
        return f"The assistant is switched off for the bot ({ASK_ENV}=0)."
    try:
        answer = chat.ask([*_turns, {"role": "user", "content": question}])
    except (chat.Refused, client.LLMUnavailable) as exc:
        return f"The assistant could not answer: {exc}"
    _turns.append({"role": "user", "content": question})
    _turns.append({"role": "assistant", "content": answer.text})
    looked = ", ".join(dict.fromkeys(str(u.get("name")) for u in answer.used))
    return f"{answer.text}\n\n{answer.model} via {answer.host}" + (
        f" · looked at: {looked}" if looked else ""
    )


def forget(_: str = "") -> str:
    _turns.clear()
    return "Forgotten. The next question starts fresh."
