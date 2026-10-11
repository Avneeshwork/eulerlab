"""`make gap-signal` — tonight's decision for the registered gap strategy.

`nifty_calm_rise_overnight` buys the Nifty future at the close after a GREEN
day on which India VIX fell (research 072). The evening files arrive hours
after the close, so they cannot place that order. This reads the two indices
live from Kite a few minutes before the close and sends the decision to
Telegram: the strategy's name, and what to do.

Run it between 15:15 and 15:25 IST on a trading day. Before that the candle is
not close to final (A-046); after 15:30 the close it would trade at has gone.
It says which it is rather than refusing, because a late message that says
"too late to act" is more use than silence.

It decides and reports. It places no order: there is no live futures path in
this project (T-4022), and the paper deployments trade equities.

Needs a Kite token minted today (`make kite-login`). Without one it says so,
on Telegram too, since a missing signal is otherwise indistinguishable from
"no trade tonight".
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from eulerlab import notify
from eulerlab.research import gap_forecast as gf

NIFTY, VIX = "NSE:NIFTY 50", "NSE:INDIA VIX"
IST = ZoneInfo("Asia/Kolkata")
WINDOW = ((15, 15), (15, 30))
"""When the decision is both nearly final and still tradable, IST."""


@dataclass(frozen=True)
class Live:
    nifty_open: float
    nifty_last: float
    vix_open: float
    vix_last: float

    def as_day(self, day: date) -> gf.Day:
        return gf.Day(day, self.nifty_open, self.nifty_last, self.vix_open, self.vix_last)


def read_live() -> tuple[Live | None, str]:
    """Today's open and last price for the Nifty 50 and India VIX, from Kite.

    Returns (values, error). An expired token is the expected failure, so it
    comes back as a message rather than an exception.
    """
    try:
        from kiteconnect import KiteConnect

        from eulerlab.broker import kite_session
        from eulerlab.quotes import _env
    except ImportError as exc:
        return None, f"kiteconnect unavailable: {exc}"

    session = kite_session.load()
    if not kite_session.is_fresh(session) or session is None:
        return None, "no Kite token minted today — run `make kite-login`"
    api_key = _env("ZERODHA_API_KEY")
    if not api_key:
        return None, "ZERODHA_API_KEY is not set"
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(session.access_token)
    try:
        payload = kite.quote([NIFTY, VIX])
    except Exception as exc:  # surfaced verbatim: it is what tells the operator to log in
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"

    values: list[float] = []
    for key in (NIFTY, VIX):
        row = payload.get(key) or {}
        opened, last = (row.get("ohlc") or {}).get("open"), row.get("last_price")
        if not isinstance(opened, int | float) or not isinstance(last, int | float) or not opened:
            return None, f"Kite returned no open or last price for {key}"
        values += [float(opened), float(last)]
    return Live(*values), ""


def timing(now: datetime) -> str:
    """'early', 'on time' or 'late' against the decision window, in IST."""
    ist = now.astimezone(IST)
    clock = (ist.hour, ist.minute)
    if ist.weekday() >= 5:
        return "late"
    if clock < WINDOW[0]:
        return "early"
    return "on time" if clock < WINDOW[1] else "late"


def compose(live: Live, now: datetime) -> str:
    """The Telegram text: the strategy's name, what it saw, what to do."""
    day = live.as_day(now.astimezone(IST).date())
    buy = gf.predict(gf.Model.JOINT, day) == gf.UP
    candle = {gf.UP: "GREEN", gf.DOWN: "RED", None: "flat"}[day.candle]
    vix = {gf.UP: "rose", gf.DOWN: "fell", None: "is flat"}[day.vix_move()]
    seen = (
        f"Nifty 50 {live.nifty_last:,.2f} against an open of {live.nifty_open:,.2f} ({candle})\n"
        f"India VIX {live.vix_last:.2f} against an open of {live.vix_open:.2f} ({vix})"
    )
    if buy:
        action = (
            "ACTION: BUY the near-month Nifty future at the close.\nEXIT: SELL at tomorrow's open."
        )
    else:
        action = "ACTION: none tonight. The rule needs a GREEN day with VIX down."
    when = timing(now)
    note = {
        "early": "\n\nRead before 15:15 IST: the candle can still change. Run again nearer the close.",
        "late": "\n\nRead after the close: too late to act on tonight.",
        "on time": "",
    }[when]
    stamp = now.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
    return f"SIGNAL · {gf.CALM_RISE_TITLE}\n{stamp}\n\n{seen}\n\n{action}{note}\n\nNot an order: nothing was placed."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gap-signal")
    parser.add_argument("--dry-run", action="store_true", help="print the message, send nothing")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    live, error = read_live()
    if live is None:
        text = f"SIGNAL · {gf.CALM_RISE_TITLE}\n\nNo decision tonight: {error}"
        code = 1
    else:
        text, code = compose(live, now), 0
    print(text)
    if args.dry_run:
        return code
    delivery = notify.send(text)
    print(f"\ntelegram: {'sent' if delivery.sent else 'NOT sent — ' + delivery.reason}")
    return code if delivery.sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
