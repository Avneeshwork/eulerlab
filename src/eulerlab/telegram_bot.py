"""Words the operator can send the Telegram bot, and what each answers.

`deploy/signals.py` and `research/gap_signal.py` push messages out. This is the
other direction (operator, 2026-10-11: "define terms i can use to interact
with telegram"; 2026-10-12: "more generalized and more features make it
broad"): type a word to the bot, get the current state back.

    Deployments   status · pnl · positions [n] · orders [n] · next [n]
    Market        market · movers · price SYMBOL · company SYMBOL · news SYMBOL
    Research      signal · strategies [word] · results ID · trials
    Machine       brief · data · jobs · kite · kill
    Assistant     ask QUESTION · forget
    help [word]

`COMMANDS` is the list; `help` prints it with what each word answers.

### How a message is read

* A leading slash is optional (`/status` and `status` are the same), so the
  words also work from Telegram's command menu, which `register_menu` fills.
* A word can be shortened: its listed short form (`pos`, `p`), or any start of
  it that fits one word only (`mov`).
* `[n]` is a deployment's number from `status`, or part of its name (`nifty`).
* A word that is nearly right gets "did you mean". A sentence that starts
  with no word at all (three words or more, or ending in a question mark)
  goes to the assistant, as `ask` does.
* A long answer arrives as several messages, split between lines, not cut.

### Every word is read-only

Nothing here places, changes or stops an order, and nothing can be added that
does without a decision recorded first (ADR-063, ADR-068). A chat is a weak
place to hold that power: a phone left unlocked, or a token pasted in the
wrong place, would be enough. `CLAUDE.md` puts kill switches in a separate
process with separate credentials, and this bot is neither. `kill` reports
the switch; it cannot move it.

### Only the operator is answered

A message is answered only when it comes from `TELEGRAM_CHAT_ID`, the chat the
signals already go to. Anything else is dropped without a reply, so the bot
gives a stranger nothing, not even confirmation that it is listening.

### Running it

The API server starts the listener with itself (`EULERLAB_TELEGRAM_BOT=0`
turns that off); `make telegram-bot` runs it alone. Telegram allows one
listener per bot, so the `telegram_bot` file lock decides which process it is.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eulerlab import notify, telegram_words

API = "https://api.telegram.org/bot{token}/{method}"
OFFSET_FILE = Path("data/derived/.telegram_offset")
POLL_SECONDS = 25
"""Long-poll length. Telegram holds the request open until a message arrives."""

CHUNK = 3500
"""Characters per message. Telegram's limit is 4096."""

KEYBOARD = (
    ("status", "pnl", "brief"),
    ("market", "movers", "signal"),
    ("data", "jobs", "help"),
)
"""The words offered as buttons under the text box, for a phone."""

Handler = Callable[[str], str]


@dataclass(frozen=True)
class Command:
    """One word the bot answers."""

    what: str
    handler: Handler
    group: str
    short: tuple[str, ...] = ()
    usage: str = ""
    """How to send it, when it takes something after the word."""


# --- what each word answers -------------------------------------------------------


def _deployments() -> list[Any]:
    from eulerlab.deploy import deployments as store

    return [d for d in store.all_deployments() if d.status in ("active", "halted")]


def _pick(arg: str) -> tuple[Any, dict[str, Any]] | str:
    """The deployment `arg` names, and its state.

    `arg` is a number as `status` lists them (1 when empty), or part of a
    deployment's strategy name or id.
    """
    from eulerlab.deploy import deployments as store
    from eulerlab.deploy.signals import title_of

    found = _deployments()
    if not found:
        return "No active deployments."
    wanted = arg.strip()
    if not wanted or wanted.lstrip("-").isdigit():
        index = int(wanted) if wanted else 1
        if not 1 <= index <= len(found):
            return f"There is no deployment {index}. There are {len(found)}; send `status`."
        chosen = found[index - 1]
        return chosen, (store.read_state(chosen) or {})
    named = [d for d in found if wanted.lower() in f"{d.id} {title_of(d.strategy_id)}".lower()]
    if len(named) == 1:
        return named[0], (store.read_state(named[0]) or {})
    if named:
        return f"'{wanted}' fits {len(named)} deployments. Send `status` and use the number."
    return f"'{wanted}' is not a number or part of a deployment's name. Send `status` to see them."


def _money(value: object) -> str:
    return f"₹{float(value):,.0f}" if isinstance(value, int | float) else "—"


def status(_: str = "") -> str:
    from eulerlab.deploy import deployments as store
    from eulerlab.deploy.signals import title_of

    found = _deployments()
    if not found:
        return "No active deployments."
    lines = []
    for number, deployment in enumerate(found, start=1):
        state = store.read_state(deployment) or {}
        total = state.get("total_return")
        change = f" ({float(total):+.1%})" if isinstance(total, int | float) else ""
        lines.append(
            f"{number}. {deployment.mode.upper()} · {title_of(deployment.strategy_id)}\n"
            f"   {_money(state.get('equity'))}{change} from {_money(deployment.capital)} · "
            f"{state.get('status', 'not run')} · through {state.get('traded_through') or '—'}"
        )
    return "\n".join(lines)


def positions(arg: str = "") -> str:
    picked = _pick(arg)
    if isinstance(picked, str):
        return picked
    deployment, state = picked
    book = state.get("book") or []
    if not book:
        return f"{deployment.id} holds nothing."
    rows = [
        f"{row.get('symbol')}: {row.get('quantity')} · {_money(row.get('value'))} "
        f"({float(row.get('weight') or 0):.0%})"
        for row in book[:30]
    ]
    return f"{deployment.id}\n" + "\n".join(rows) + f"\nCash {_money(state.get('cash'))}"


def orders(arg: str = "") -> str:
    from eulerlab.deploy.signals import _order_line

    picked = _pick(arg)
    if isinstance(picked, str):
        return picked
    deployment, state = picked
    fills = state.get("fills") or []
    if not fills:
        return f"{deployment.id} has placed no orders."
    last = fills[-10:]
    return (
        f"{deployment.id} — last {len(last)} of {state.get('fills_total', len(fills))}\n"
        + "\n".join(f"{f.get('day')}  {_order_line(f)}" for f in last)
    )


def upcoming(arg: str = "") -> str:
    picked = _pick(arg)
    if isinstance(picked, str):
        return picked
    deployment, state = picked
    intended = state.get("intended") or {}
    names = ", ".join(intended.get("names") or []) or "nothing"
    cut = intended.get("cut") or []
    left = f"\nLeft out, capital too small: {', '.join(cut)}" if cut else ""
    return (
        f"{deployment.id}\nNext rebalance: {state.get('next_rebalance') or 'unknown'}\n"
        f"Would hold: {names}{left}\nA preview from today's ranking, not an order."
    )


def signal(_: str = "") -> str:
    from datetime import UTC, datetime

    from eulerlab.research import gap_forecast as gf
    from eulerlab.research import gap_signal

    live, error = gap_signal.read_live()
    if live is None:
        return f"SIGNAL · {gf.CALM_RISE_TITLE}\n\nNo decision: {error}"
    return gap_signal.compose(live, datetime.now(UTC))


def data(_: str = "") -> str:
    from eulerlab.ingest import coverage

    rows = coverage.table()
    counts = coverage.summary(rows)
    behind = [r for r in rows if r.status in ("behind", "stale", "missing")]
    head = " · ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    if not behind:
        return f"Data: {head}\nEverything is up to date."
    lines = [f"{r.name}: {r.status}, last {r.last or 'never'}" for r in behind]
    return f"Data: {head}\n" + "\n".join(lines)


def strategies(arg: str = "") -> str:
    from collections import Counter

    from eulerlab.strategies import REGISTRY

    if arg.strip():
        from eulerlab.assistant import tools

        return tools._strategies({"search": arg.strip()})
    kinds = Counter(d.asset_class.value for d in REGISTRY.values())
    return (
        f"{len(REGISTRY)} strategies in the library\n"
        + "\n".join(f"{kind}: {n}" for kind, n in sorted(kinds.items()))
        + "\nSend `strategies <word>` to search them."
    )


def help_text(arg: str = "") -> str:
    """Every word by group, or how to send one word when `arg` names it."""
    word = resolve(arg.strip().lstrip("/").lower()) if arg.strip() else None
    if word:
        command = COMMANDS[word]
        lines = [f"{word} — {command.what}"]
        if command.usage:
            lines.append(f"Send: {command.usage}")
        if command.short:
            lines.append(f"Short: {', '.join(command.short)}")
        return "\n".join(lines)
    out = ["Send one of:"]
    group = ""
    for name, command in COMMANDS.items():
        if command.group != group:
            group = command.group
            out.append(f"\n{group}")
        out.append(f"{name} — {command.what}")
    out.append("\nOr ask in plain words. `help <word>` says how to send one.")
    return "\n".join(out)


COMMANDS: dict[str, Command] = {
    "status": Command(
        "every deployment: mode, strategy, equity, last day", status, "Deployments", ("st", "s")
    ),
    "pnl": Command(
        "profit and loss of each deployment, and in all",
        telegram_words.pnl,
        "Deployments",
        ("pl",),
    ),
    "positions": Command(
        "what a deployment holds",
        positions,
        "Deployments",
        ("pos", "p"),
        "positions 2, or positions nifty",
    ),
    "orders": Command(
        "a deployment's last ten orders", orders, "Deployments", ("o",), "orders 2, or orders nifty"
    ),
    "next": Command(
        "what a deployment will hold after the next rebalance",
        upcoming,
        "Deployments",
        ("n",),
        "next 2",
    ),
    "market": Command(
        "NSE now: how many up and down, the trend, volatility",
        telegram_words.market,
        "Market",
        ("m",),
    ),
    "movers": Command(
        "the biggest rises, falls and unusual turnover", telegram_words.movers, "Market"
    ),
    "price": Command(
        "one stock: price now, last close, range over a year",
        telegram_words.price,
        "Market",
        ("px", "quote", "q"),
        "price RELIANCE, or price tata motors",
    ),
    "company": Command(
        "one company: size, valuation, growth, debt, promoters",
        telegram_words.company,
        "Market",
        ("co", "c"),
        "company INFY",
    ),
    "news": Command(
        "the newest held headlines that name a company",
        telegram_words.news,
        "Market",
        (),
        "news INFY",
    ),
    "signal": Command(
        "tonight's decision for the Nifty gap strategy", signal, "Research", ("sig",)
    ),
    "strategies": Command(
        "how many strategies are in the library, or a search of them",
        strategies,
        "Research",
        ("strat",),
        "strategies momentum",
    ),
    "results": Command(
        "one strategy's latest and best backtest",
        telegram_words.results,
        "Research",
        ("res", "r"),
        "results <strategy id>, or part of its name",
    ),
    "trials": Command(
        "how many strategy configurations have been tried", telegram_words.trials, "Research"
    ),
    "brief": Command(
        "everything at once: money, market, data, logins, jobs",
        telegram_words.brief,
        "Machine",
        ("b",),
    ),
    "data": Command("which datasets are behind", data, "Machine", ("d",)),
    "jobs": Command(
        "the scheduled jobs and how their last run ended", telegram_words.jobs, "Machine"
    ),
    "kite": Command("whether today's Kite login is valid", telegram_words.kite, "Machine"),
    "kill": Command(
        "whether the kill switch is tripped, and its limits", telegram_words.kill, "Machine"
    ),
    "agents": Command(
        "each agent, on or off, and how its last run ended", telegram_words.agents, "Agents"
    ),
    "instruct": Command(
        "save a brief that steers an agent (it cannot change limits)",
        telegram_words.instruct,
        "Agents",
        (),
        "instruct research overnight returns in midcaps",
    ),
    "feedback": Command(
        "tell the agents something: a rule becomes a lesson, the rest a head's task",
        telegram_words.feedback,
        "Agents",
        (),
        "feedback never short stocks under 50 rupees",
    ),
    "outlook": Command("the latest market brief", telegram_words.outlook, "Agents"),
    "inbox": Command(
        "what the agents are waiting for you to decide", telegram_words.inbox_word, "Agents"
    ),
    "ask": Command(
        "a question in plain words, answered by the assistant",
        telegram_words.ask,
        "Assistant",
        ("a",),
        "ask which deployment did best this month?",
    ),
    "forget": Command(
        "drop the conversation with the assistant", telegram_words.forget, "Assistant"
    ),
    "help": Command("this list", help_text, "Help", ("h", "?"), "help price"),
}
"""Every word the bot answers. All read-only except `instruct`, which saves an agent brief
(ADR-085), and `feedback`, which saves a lesson or a head's task (ADR-152); see the module
docstring."""

SENTENCE_WORDS = 3
"""Words in a message before it is read as a question and not a mistyped word."""


def resolve(word: str) -> str | None:
    """The command `word` means: itself, a short form, or a start only one word has."""
    if word in COMMANDS:
        return word
    for name, command in COMMANDS.items():
        if word in command.short:
            return name
    starts = [name for name in COMMANDS if len(word) > 1 and name.startswith(word)]
    return starts[0] if len(starts) == 1 else None


def _run(word: str, arg: str) -> str:
    try:
        return COMMANDS[word].handler(arg)
    except Exception as exc:  # a broken handler answers with its error, not with silence
        return f"{word} failed: {type(exc).__name__}: {str(exc)[:200]}"


def answer(text: str) -> str:
    """The reply to one message. Unknown words get the list, never silence."""
    import difflib

    parts = text.strip().split(maxsplit=1)
    if not parts:
        return help_text()
    typed = parts[0].lstrip("/").split("@", 1)[0].lower()
    if typed == "start":
        typed = "help"
    word = resolve(typed)
    if word is not None:
        return _run(word, parts[1] if len(parts) > 1 else "")
    near = difflib.get_close_matches(typed, COMMANDS, n=1, cutoff=0.75)
    if near:
        return f"I do not know '{parts[0]}'. Did you mean `{near[0]}`?"
    # Not a word and not close to one. A whole sentence is a question for the
    # assistant; one or two stray words are more likely a slip, and a slip
    # should not go to a model.
    sentence = len(text.split()) >= SENTENCE_WORDS or text.strip().endswith("?")
    if sentence and not text.lstrip().startswith("/") and telegram_words.ask_enabled():
        return _run("ask", text.strip())
    return f"I do not know '{parts[0]}'.\n\n{help_text()}"


def chunks(text: str, limit: int = CHUNK) -> Iterator[str]:
    """`text` in pieces of at most `limit` characters, broken between lines."""
    piece = ""
    for line in text.splitlines():
        while len(line) > limit:  # one line longer than a message: cut it
            if piece:
                yield piece
                piece = ""
            yield line[:limit]
            line = line[limit:]
        if piece and len(piece) + 1 + len(line) > limit:
            yield piece
            piece = line
        else:
            piece = f"{piece}\n{line}" if piece else line
    if piece.strip():
        yield piece


# --- talking to Telegram -------------------------------------------------------------


def _call(method: str, params: Mapping[str, Any], timeout: int) -> dict[str, Any]:
    token = notify._env(notify.TOKEN_ENV)
    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=urllib.parse.urlencode(params).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return parsed


def authorised(message: Mapping[str, Any]) -> bool:
    """Whether this message is from the operator's own chat."""
    chat = (message.get("chat") or {}).get("id")
    return chat is not None and str(chat) == notify._env(notify.CHAT_ENV)


def handle(update: Mapping[str, Any]) -> str | None:
    """The reply for one update, or None when it is not ours to answer."""
    message = update.get("message") or {}
    text = message.get("text")
    if not isinstance(text, str) or not authorised(message):
        return None
    return answer(text)


def register_menu() -> None:
    """Fill Telegram's command menu from `COMMANDS`. Best effort."""
    menu = [{"command": word, "description": c.what[:256]} for word, c in COMMANDS.items()]
    try:
        _call("setMyCommands", {"commands": json.dumps(menu)}, timeout=15)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return


def reply(text: str) -> bool:
    """Send an answer to the operator's chat, in as many messages as it needs.

    Sent here and not through `notify.send`, which cuts a long message short:
    right for a traceback, wrong for an answer someone asked for.
    """
    chat = notify._env(notify.CHAT_ENV)
    markup = json.dumps({"keyboard": [list(row) for row in KEYBOARD], "resize_keyboard": True})
    sent = True
    for piece in chunks(text):
        try:
            done = _call(
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": piece,
                    "reply_markup": markup,
                    "disable_web_page_preview": "true",
                },
                timeout=15,
            )
            sent = sent and bool(done.get("ok"))
        except (urllib.error.URLError, TimeoutError, ValueError):
            sent = False
    return sent


def _typing() -> None:
    """Show "typing" while an answer is worked out. Best effort."""
    try:
        _call(
            "sendChatAction",
            {"chat_id": notify._env(notify.CHAT_ENV), "action": "typing"},
            timeout=5,
        )
    except (urllib.error.URLError, TimeoutError, ValueError):
        return


def _read_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def enabled() -> bool:
    return os.environ.get("EULERLAB_TELEGRAM_BOT", "1") != "0" and notify.configured()


def listen(stop: threading.Event) -> None:
    """Answer messages until `stop` is set. One listener at a time.

    Holds the `telegram_bot` lock: Telegram rejects a second poller, and the
    API's reloader starts a second process. A process that cannot take the
    lock returns at once and leaves the other to it.
    """
    from eulerlab.ingest.filelock import Busy, exclusive

    try:
        with exclusive("telegram_bot", wait=False, what="telegram bot listener"):
            register_menu()
            offset = _read_offset()
            while not stop.is_set():
                try:
                    updates = _call(
                        "getUpdates",
                        {"offset": offset, "timeout": POLL_SECONDS},
                        timeout=POLL_SECONDS + 10,
                    )
                except (urllib.error.URLError, TimeoutError, ValueError):
                    stop.wait(10)
                    continue
                for update in updates.get("result") or []:
                    offset = int(update["update_id"]) + 1
                    if authorised(update.get("message") or {}):
                        _typing()
                    text = handle(update)
                    if text:
                        reply(text)
                    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
                    OFFSET_FILE.write_text(str(offset), encoding="utf-8")
    except Busy:
        return


def main() -> int:
    """`make telegram-bot`: listen in the foreground until interrupted."""
    if not notify.configured():
        print(f"{notify.TOKEN_ENV} and {notify.CHAT_ENV} are not set in .env")
        return 1
    print("listening. Send the bot one of: " + ", ".join(COMMANDS))
    stop = threading.Event()
    try:
        listen(stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
