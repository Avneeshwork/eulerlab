"""`make kite-readonly`: prove the Kite adapter can talk to the real API without sending anything (T-3336).

It reads, through the same `KiteBroker` the order path uses: who is logged in,
the funds available, open positions, today's orders and holdings. Every write
method of the client is replaced by one that raises, so this command cannot
place, modify or cancel an order even by mistake.

What it proves: the session and key work, and the adapter's read paths
(`positions`, `open_orders`) parse Kite's real replies. What it does not prove:
that Kite accepts the orders the adapter builds. That needs one small supervised
order in a market session, on the operator's word (T-3336 stays open until then).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from eulerlab.broker.kite import KiteBroker


class WriteRefused(RuntimeError):
    """The read-only check tried to send something. It never should."""


class ReadOnly:
    """A Kite client with every write turned into an error."""

    _WRITES = frozenset(
        {"place_order", "modify_order", "cancel_order", "exit_order", "place_gtt", "modify_gtt"}
    )

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name in self._WRITES or name.startswith(("place_", "modify_", "cancel_", "delete_")):
            msg = f"read-only check refused {name}"
            raise WriteRefused(msg)
        return getattr(self._client, name)


@dataclass
class Result:
    ok: bool = True
    lines: list[str] = field(default_factory=list)

    def step(self, name: str, call: Callable[[], str]) -> None:
        try:
            self.lines.append(f"ok    {name}: {call()}")
        except Exception as exc:
            self.ok = False
            self.lines.append(f"FAIL  {name}: {type(exc).__name__}: {str(exc)[:160]}")


def check(client: Any) -> Result:
    """Run every read. `client` is a logged-in `KiteConnect` (or a fake in tests)."""
    safe = ReadOnly(client)
    broker = KiteBroker(safe)
    out = Result()
    out.step("profile", lambda: str(safe.profile().get("user_id", "?")))
    out.step(
        "funds",
        lambda: (
            f"equity available Rs {float(safe.margins('equity').get('available', {}).get('live_balance', 0)):,.0f}"
        ),
    )
    out.step("positions (adapter)", lambda: f"{len(broker.positions())} symbol(s) held net")
    out.step("today's orders (adapter)", lambda: f"{len(broker.open_orders())} open")
    out.step("holdings", lambda: f"{len(safe.holdings())} holding(s)")
    return out


def main() -> int:
    from eulerlab.broker import kite_session
    from eulerlab.quotes import _env

    session = kite_session.load()
    if not kite_session.is_fresh(session) or session is None:
        print("no Kite session for today: run `make kite-login` first")
        return 1
    api_key = _env("ZERODHA_API_KEY")
    if not api_key:
        print("ZERODHA_API_KEY is not set in .env")
        return 1
    try:
        from kiteconnect import KiteConnect
    except ImportError as exc:
        print(f"kiteconnect unavailable: {exc}")
        return 1
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(session.access_token)
    result = check(kite)
    print("\n".join(result.lines))
    print(
        "\nread-only check passed; nothing was sent."
        if result.ok
        else "\nread-only check FAILED; nothing was sent."
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
