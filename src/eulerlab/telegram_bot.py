"""Words the operator can send the Telegram bot, and what each answers.

`deploy/signals.py` and `research/gap_signal.py` push messages out. This is the
other direction (operator, 2026-10-11: "define terms i can use to interact
with telegram"): type a word to the bot, get the current state back.

    status          every deployment: mode, strategy, equity, return, last day
    positions [n]   what deployment n holds (n from `status`; default 1)
    orders [n]      its last ten orders
    next [n]        what it will hold after the next rebalance, and when
    signal          tonight's decision for the Nifty gap strategy
    data            which datasets are behind
    strategies      how many strategies are in the library, by kind
    help            this list

A leading slash is optional (`/status` and `status` are the same), so the
words also work from Telegram's command menu, which `register_menu` fills.

### Every word is read-only

Nothing here places, changes or stops an order, and nothing can be added that
does without a decision recorded first. A chat is a weak place to hold that
power: a phone left unlocked, or a token pasted in the wrong place, would be
enough. `CLAUDE.md` puts kill switches in a separate process with separate
credentials, and this bot is neither.

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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from eulerlab import notify

API = "https://api.telegram.org/bot{token}/{method}"
OFFSET_FILE = Path("data/derived/.telegram_offset")
POLL_SECONDS = 25
"""Long-poll length. Telegram holds the request open until a message arrives."""

Handler = Callable[[str], str]


# --- what each word answers -------------------------------------------------------


def _deployments() -> list[Any]:
    from eulerlab.deploy import deployments as store

    return [d for d in store.all_deployments() if d.status in ("active", "halted")]


def _pick(arg: str) -> tuple[Any, dict[str, Any]] | str:
    """Deployment number `arg` (1-based, as `status` lists them) and its state."""
    from eulerlab.deploy import deployments as store

    found = _deployments()
    if not found:
        return "No active deployments."
    try:
        index = int(arg) if arg.strip() else 1
    except ValueError:
        return f"'{arg}' is not a number. Send `status` to see the numbers."
    if not 1 <= index <= len(found):
        return f"There is no deployment {index}. There are {len(found)}; send `status`."
    chosen = found[index - 1]
    return chosen, (store.read_state(chosen) or {})


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


def strategies(_: str = "") -> str:
    from collections import Counter

    from eulerlab.strategies import REGISTRY

    kinds = Counter(d.asset_class.value for d in REGISTRY.values())
    return f"{len(REGISTRY)} strategies in the library\n" + "\n".join(
        f"{kind}: {n}" for kind, n in sorted(kinds.items())
    )


def help_text(_: str = "") -> str:
    return "Send one of:\n" + "\n".join(f"{word} — {what}" for word, (what, _h) in COMMANDS.items())


COMMANDS: dict[str, tuple[str, Handler]] = {
    "status": ("every deployment: mode, strategy, equity, last day", status),
    "positions": ("what a deployment holds; `positions 2` for the second", positions),
    "orders": ("its last ten orders", orders),
    "next": ("what it will hold after the next rebalance", upcoming),
    "signal": ("tonight's decision for the Nifty gap strategy", signal),
    "data": ("which datasets are behind", data),
    "strategies": ("how many strategies are in the library", strategies),
    "help": ("this list", help_text),
}
"""Every word the bot answers. All read-only; see the module docstring."""


def answer(text: str) -> str:
    """The reply to one message. Unknown words get the list, never silence."""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return help_text()
    word = parts[0].lstrip("/").split("@", 1)[0].lower()
    if word == "start":
        word = "help"
    found = COMMANDS.get(word)
    if found is None:
        return f"I do not know '{parts[0]}'.\n\n{help_text()}"
    try:
        return found[1](parts[1] if len(parts) > 1 else "")
    except Exception as exc:  # a broken handler answers with its error, not with silence
        return f"{word} failed: {type(exc).__name__}: {str(exc)[:200]}"


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
    menu = [{"command": word, "description": what[:256]} for word, (what, _h) in COMMANDS.items()]
    try:
        _call("setMyCommands", {"commands": json.dumps(menu)}, timeout=15)
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
                    reply = _call(
                        "getUpdates",
                        {"offset": offset, "timeout": POLL_SECONDS},
                        timeout=POLL_SECONDS + 10,
                    )
                except (urllib.error.URLError, TimeoutError, ValueError):
                    stop.wait(10)
                    continue
                for update in reply.get("result") or []:
                    offset = int(update["update_id"]) + 1
                    text = handle(update)
                    if text:
                        notify.send(text)
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
