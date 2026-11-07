"""Paper books for the gated stock rules of research 168-171 (ADR-147).

H-0132, H-0118, H-0121, H-0115 and H-0124 at 5x MIS; H-0146 at 1x (₹1 lakh
a position on ₹10 lakh, research 171; it reads no news, ban or holiday data).

Research 168-170 gated these at Zerodha 5x MIS size: ₹5 lakh a position on
₹1 lakh of margin, at most ten open. Each generator here re-applies the exact
rule function the gate judged (`intraday/mft_screen`, `intraday/quant_screen`)
to minute files that start after the holdout end, and returns `rule_book`'s
trade shape for `study_book.run`.

The deployment's capital is the margin. A position is half of it in notional
(₹5 lakh on ₹10 lakh), so ten open positions are 5x the capital, as
backtested. The rules rank the 100 most traded stocks over the previous 20
sessions, so a book trades nothing for its first 20 sessions after the holdout
end; H-0132 also needs 20 overnight moves (21 sessions). Only minute files
that start after the holdout end are opened, for stocks and for the Nifty.

Each run reads every F&O stock's minute files since the holdout end, which is
slow (the same cost as H-0065's book, T-4481).
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from datetime import date
from itertools import pairwise
from typing import Any

from eulerlab.intraday import mft_screen as mft

POSITION_SHARE = 0.5
"""A position's notional as a share of the margin: ₹5 lakh on ₹10 lakh (research 168)."""
ONE_X_SHARE = 0.1
"""H-0146 at 1x: ₹1 lakh a position on ₹10 lakh of capital (research 171)."""

Trade = dict[str, Any]
Rule = Callable[..., Iterator[mft.Signal]]


def _onex(hypothesis: str) -> Rule:
    """A research-171 rule in the shape the book calls: (market, day, delay)."""
    from eulerlab.intraday import onex_screen as onex

    _, rule = onex.RULES[hypothesis]

    def call(mk: mft.Market, day: date, delay: int = 0) -> Iterator[mft.Signal]:
        del delay
        return rule(onex.Context(mk, {}, {}, frozenset()), day)

    return call


def rules() -> dict[str, Rule]:
    from eulerlab.intraday import quant_screen as quant

    return {
        "H-0146": _onex("H-0146"),
        "H-0132": quant.RULES["H-0132"][1],
        "H-0118": mft.RULES["H-0118"][1],
        "H-0121": mft.RULES["H-0121"][1],
        "H-0115": mft.RULES["H-0115"][1],
        "H-0124": mft.RULES["H-0124"][1],
    }


IDS = ("H-0132", "H-0146", "H-0118", "H-0121", "H-0115", "H-0124")
SHARE = {h: ONE_X_SHARE if h == "H-0146" else POSITION_SHARE for h in IDS}


def _nifty_minutes(*, since: date, through: date) -> dict[date, tuple[float, ...]]:
    """Nifty 50 minute closes from files that start after `since`."""
    import pyarrow.parquet as pq

    from eulerlab.ingest import landing_reader
    from eulerlab.intraday import india_papers as ip
    from eulerlab.intraday import research_screen as rs

    rows: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    for name in sorted(landing_reader.available("kite_index_minute", "NIFTY50/*.parquet")):
        if rs._file_start(name) <= since or rs._file_start(name) > through:
            continue
        table = pq.read_table(
            io.BytesIO(landing_reader.read(name, cache=False)),
            columns=["ts", "open", "high", "low", "close"],
        )
        columns = [table.column(c).to_pylist() for c in table.column_names]
        for stamp, open_, high, low, close in zip(*columns, strict=True):
            if None in (stamp, open_, high, low, close):
                continue
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < ip.MINUTES and stamp[:10] <= through.isoformat():
                rows.setdefault(stamp[:10], {})[minute] = (open_, high, low, close, 0.0)
    return {d.day: d.close for d in ip.days_from_rows(rows)}


def market(
    snaps: dict[str, dict[date, Any]],
    nifty: dict[date, tuple[float, ...]],
    official: dict[date, float],
) -> mft.Market:
    """The research `Market`, built only from what the book has seen."""
    window = sorted({d for days in snaps.values() for d in days})
    ordered = sorted(official)
    prev = {b: official[a] for a, b in pairwise(ordered)}
    return mft.Market(
        snaps=snaps,
        sessions=[d for d in window if d in nifty],
        nifty=nifty,
        nifty_prev=prev,
        beta={},
        liquid=mft.liquidity(snaps, window),
        industry={},
        previous={b: a for a, b in pairwise(window)},
        nifty_close=official,
    )


def trades_from(
    rule: Rule, mk: mft.Market, *, start: date, capital: float, share: float = POSITION_SHARE
) -> tuple[list[Trade], list[date]]:
    """The rule's signals from `start`, through the ten-open book, as `rule_book` trades."""
    from eulerlab.deploy import rule_book

    days = [d for d in mk.sessions if d >= start]
    notional = capital * share
    out: list[Trade] = []
    for sig in mft.book([s for day in days for s in rule(mk, day, 0)]):
        quantity = int(notional / sig.entry) if sig.entry > 0 else 0
        if quantity:
            trade = rule_book._trade(
                sig.day, sig.symbol, sig.direction, quantity, sig.entry, sig.exit, sig.entry_minute
            )
            out.append(trade)
    return out, mk.sessions


def generator(strategy_id: str) -> Callable[..., tuple[list[Trade], list[date]]]:
    def generate(
        *, start: date, through: date, since: date, capital: float
    ) -> tuple[list[Trade], list[date]]:
        from eulerlab.deploy import rule_book
        from eulerlab.intraday import cross_section as cs
        from eulerlab.intraday import minute_six_screen as six

        snaps: dict[str, dict[date, Any]] = {}
        for symbol in cs.universe():
            found = {
                d.day: s
                for d in rule_book._days(symbol, since=since, through=through)
                if (s := six.snap(d)) is not None
            }
            if found:
                snaps[symbol] = found
        mk = market(snaps, _nifty_minutes(since=since, through=through), mft._official_closes())
        return trades_from(
            rules()[strategy_id], mk, start=start, capital=capital, share=SHARE[strategy_id]
        )

    return generate
