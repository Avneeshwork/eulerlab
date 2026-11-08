"""One card language and one screen for daily-bar event rules (ADR-150, research 177).

Before this, each research batch (research 166-176) needed a new hand-written
screen module, so only a person could test a new idea. Here a rule is data: a
card's `engine:` block names its signals, its side, how it ranks candidates
and how long it holds. One engine runs every card in research 173's frame:

- the 500 most traded NSE stocks each day by 20-session traded value,
  computed from that day's data only (no list of today's stocks);
- a stock in series BE/BZ (trade-for-trade) the previous session is skipped,
  and so is one priced under `cs.MIN_PRICE` (research 174);
- intraday: official open to official close at cash intraday costs, ₹1 lakh a
  position, at most ten a day, best rank first;
- swing: delivery, long only, buy at an official open, sell at the official
  close `hold` sessions later, ₹1 lakh a position, at most ten open;
- the window starts on the first day every signal's data exists and ends at
  `cs.DATA_END`. The card cannot choose it.

**No lookahead, by construction.** A signal that uses a session's close needs
`lag >= 1` (a session before the entry); only the entry morning's open (`gap`)
and disclosures dated before the open (`results_morning`, `bulk_buy`,
`bulk_sell`, `promoter_buy`) may use `lag = 0`. A spec that breaks this does
not parse.

The ten rules of research 176 are written here as specs (`REFERENCE`), and a
test holds the engine to their published numbers.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eulerlab.filecache import FileMemo, read_yaml
from eulerlab.intraday import daily_more_screen as dm
from eulerlab.intraday import daily_universe_screen as du
from eulerlab.intraday import screen_common as sc

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

HYPOTHESES = Path("hypotheses")
FIRST = dm.FIRST
REPORTS_FIRST = dm.REPORTS_FIRST
END = dm.END
MIN_TRADES = 100
# ASSUMPTION: A-121 — this and the thresholds in `checks` are chosen by hand.
"""Fewer trades or positions than this and the screen's Sharpe is not worth reading."""

SignalName = Literal[
    "gap",
    "ret",
    "day_return",
    "delivery_ratio",
    "value_ratio",
    "at_high",
    "at_low",
    "results_morning",
    "bulk_buy",
    "bulk_sell",
    "promoter_buy",
]


class SignalInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    what: str
    min_lag: int
    boolean: bool
    first: date


SIGNALS: dict[str, SignalInfo] = {
    "gap": SignalInfo(
        what="open of the session / previous close - 1 (lag 0 = the entry morning's gap)",
        min_lag=0,
        boolean=False,
        first=FIRST,
    ),
    "ret": SignalInfo(
        what="close / close n sessions earlier - 1, ending lag sessions before entry",
        min_lag=1,
        boolean=False,
        first=FIRST,
    ),
    "day_return": SignalInfo(
        what="close / open - 1 of one session (open to close move)",
        min_lag=1,
        boolean=False,
        first=FIRST,
    ),
    "delivery_ratio": SignalInfo(
        what="delivery % of the session / its previous 20-session mean",
        min_lag=1,
        boolean=False,
        first=FIRST,
    ),
    "value_ratio": SignalInfo(
        what="traded value of the session / its previous 20-session mean",
        min_lag=1,
        boolean=False,
        first=FIRST,
    ),
    "at_high": SignalInfo(
        what="close at or above the highest close of the n sessions before it",
        min_lag=1,
        boolean=True,
        first=FIRST,
    ),
    "at_low": SignalInfo(
        what="close at or below the lowest close of the n sessions before it",
        min_lag=1,
        boolean=True,
        first=FIRST,
    ),
    "results_morning": SignalInfo(
        what="financial results disclosed after the previous 15:30 and before 09:15",
        min_lag=0,
        boolean=True,
        first=REPORTS_FIRST,
    ),
    "bulk_buy": SignalInfo(
        what="net bulk-deal buying (rupees) disclosed the evening before the session",
        min_lag=0,
        boolean=False,
        first=REPORTS_FIRST,
    ),
    "bulk_sell": SignalInfo(
        what="net bulk-deal selling (rupees) disclosed the evening before the session",
        min_lag=0,
        boolean=False,
        first=REPORTS_FIRST,
    ),
    "promoter_buy": SignalInfo(
        what="a SAST promoter acquisition (share of equity) disclosed before the session",
        min_lag=0,
        boolean=False,
        first=REPORTS_FIRST,
    ),
}
"""The vocabulary. A new signal is a line here and a branch in `Engine.value`."""

EVENT_SIGNALS = frozenset({"results_morning", "bulk_buy", "bulk_sell", "promoter_buy"})
"""Signals that are dated events: a rule using one is checked only on those days."""


class Signal(BaseModel):
    """One signal of one stock, read `lag` sessions before the entry session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal: SignalName
    lag: int = Field(0, ge=0, le=5)
    n: int = Field(1, ge=1, le=260)
    """Window for `ret`, `at_high` and `at_low`; ignored by the rest."""
    absolute: bool = False

    @model_validator(mode="after")
    def _no_lookahead(self) -> Signal:
        need = SIGNALS[self.signal].min_lag
        if self.lag < need:
            msg = f"{self.signal} uses a session's close: lag must be >= {need}, not {self.lag}"
            raise ValueError(msg)
        return self


class Condition(Signal):
    op: Literal[">=", "<=", ">", "<"] | None = None
    value: float | None = None

    @model_validator(mode="after")
    def _complete(self) -> Condition:
        if (self.op is None) != (self.value is None):
            msg = f"{self.signal}: give both op and value, or neither"
            raise ValueError(msg)
        return self


class Rank(Signal):
    order: Literal["desc", "asc"] = "desc"


class RuleSpec(BaseModel):
    """A card's `engine:` block."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["intraday", "swing"]
    hold: int = Field(0, ge=0, le=60)
    """Sessions held, swing only (exit at the close `hold` sessions after entry)."""
    side: Literal["long", "short", "against", "with"]
    """`against`/`with` trade against or with the sign of `direction_of`."""
    direction_of: Signal | None = None
    when: list[Condition] = Field(min_length=1, max_length=5)
    rank_by: Rank

    @model_validator(mode="after")
    def _consistent(self) -> RuleSpec:
        if self.kind == "swing" and not 2 <= self.hold <= 60:
            msg = "a swing rule holds 2 to 60 sessions"
            raise ValueError(msg)
        if self.kind == "intraday" and self.hold:
            msg = "an intraday rule closes the same session: hold must be 0"
            raise ValueError(msg)
        if self.kind == "swing" and self.side == "short":
            msg = "swing rules are delivery, long only (no overnight cash shorts)"
            raise ValueError(msg)
        if self.side in ("against", "with") and self.direction_of is None:
            msg = f"side {self.side} needs direction_of"
            raise ValueError(msg)
        return self

    @property
    def signals(self) -> list[Signal]:
        out: list[Signal] = [*self.when, self.rank_by]
        if self.direction_of is not None:
            out.append(self.direction_of)
        return out

    @property
    def first(self) -> date:
        """The first entry day every signal's data exists for."""
        return max(SIGNALS[s.signal].first for s in self.signals)

    def fingerprint(self) -> str:
        """Same rule, same fingerprint, however the YAML was ordered."""
        body = self.model_dump(mode="json")
        body["when"] = sorted(body["when"], key=lambda c: json.dumps(c, sort_keys=True))
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]

    def describe(self) -> str:
        def one(s: Signal) -> str:
            name = s.signal + (f"({s.n})" if s.signal in ("ret", "at_high", "at_low") else "")
            name = f"|{name}|" if s.absolute else name
            return name + (f"[lag {s.lag}]" if s.lag else "")

        parts = []
        for c in self.when:
            parts.append(one(c) + (f" {c.op} {c.value:g}" if c.op and c.value is not None else ""))
        side: str = self.side
        if self.direction_of is not None and self.side in ("against", "with"):
            side = f"{self.side} {one(self.direction_of)}"
        hold = "open to close" if self.kind == "intraday" else f"hold {self.hold} sessions"
        return (
            f"{self.kind}: when {' and '.join(parts)}; {side}; {hold}; "
            f"rank by {one(self.rank_by)} {self.rank_by.order}"
        )


def _c(signal: str, op: str | None = None, value: float | None = None, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"signal": signal, **kw}
    if op is not None:
        out |= {"op": op, "value": value}
    return out


_DELIVERY_FALL = [_c("ret", "<=", -0.03, lag=1), _c("delivery_ratio", "<=", 0.5, lag=1)]
_DELIVERY_RISE = [_c("ret", ">=", 0.03, lag=1), _c("delivery_ratio", ">=", 2.0, lag=1)]
REFERENCE: dict[str, dict[str, Any]] = {
    "H-0164": {
        "kind": "intraday",
        "side": "long",
        "when": _DELIVERY_FALL,
        "rank_by": {"signal": "delivery_ratio", "lag": 1, "order": "asc"},
    },
    "H-0165": {
        "kind": "intraday",
        "side": "long",
        "when": _DELIVERY_RISE,
        "rank_by": {"signal": "delivery_ratio", "lag": 1, "order": "desc"},
    },
    "H-0166": {
        "kind": "intraday",
        "side": "long",
        "when": [_c("bulk_buy", ">", 0.0)],
        "rank_by": {"signal": "bulk_buy", "order": "desc"},
    },
    "H-0167": {
        "kind": "intraday",
        "side": "short",
        "when": [_c("bulk_sell", ">", 0.0)],
        "rank_by": {"signal": "bulk_sell", "order": "desc"},
    },
    "H-0168": {
        "kind": "intraday",
        "side": "against",
        "direction_of": {"signal": "gap"},
        "when": [_c("results_morning"), _c("gap", ">=", 0.03, absolute=True)],
        "rank_by": {"signal": "gap", "absolute": True, "order": "desc"},
    },
    "H-0169": {
        "kind": "swing",
        "hold": 10,
        "side": "long",
        "when": [_c("bulk_buy", ">", 0.0)],
        "rank_by": {"signal": "bulk_buy", "order": "desc"},
    },
    "H-0170": {
        "kind": "swing",
        "hold": 10,
        "side": "long",
        "when": _DELIVERY_RISE,
        "rank_by": {"signal": "delivery_ratio", "lag": 1, "order": "desc"},
    },
    "H-0171": {
        "kind": "swing",
        "hold": 5,
        "side": "long",
        "when": _DELIVERY_FALL,
        "rank_by": {"signal": "delivery_ratio", "lag": 1, "order": "asc"},
    },
    "H-0172": {
        "kind": "swing",
        "hold": 20,
        "side": "long",
        "when": [
            _c("results_morning", lag=1),
            _c("gap", ">=", 0.03, lag=1),
            _c("day_return", ">", 0.0, lag=1),
            _c("delivery_ratio", ">=", 1.5, lag=1),
        ],
        "rank_by": {"signal": "gap", "lag": 1, "order": "desc"},
    },
    "H-0173": {
        "kind": "swing",
        "hold": 20,
        "side": "long",
        "when": [_c("at_high", lag=1, n=250), _c("delivery_ratio", ">=", 2.0, lag=1)],
        "rank_by": {"signal": "delivery_ratio", "lag": 1, "order": "desc"},
    },
}
"""Research 176's ten rules, as specs. Used to check the engine and to spot repeats."""


def reference_specs() -> dict[str, RuleSpec]:
    return {h: RuleSpec.model_validate(s) for h, s in REFERENCE.items()}


# --- the data ---------------------------------------------------------------------------


class Data(dm.Context):
    """Research 176's data (panel, liquidity, delivery, bulk deals, results, trade-for-trade),
    plus what the engine adds lazily: results mornings, promoter buys, traded-value ratios."""

    end: date = END
    """The last entry day. The research window stops at `cs.DATA_END`."""

    @cached_property
    def mornings(self) -> frozenset[tuple[date, str]]:
        return frozenset(dm._results_mornings(self))

    @cached_property
    def promoters(self) -> Mapping[str, Mapping[date, float]]:
        from eulerlab.intraday import nse_reports_screen as rep

        sast = [x for _, found in rep._parsed("sast", rep.promoter_buys) for x in found]
        return rep.promoter_events(sast, self.sessions)

    def by_day(self, signal: str) -> Mapping[date, frozenset[str]]:
        """{day: stocks with that event signal on it}, built once per signal."""
        cache: dict[str, dict[date, frozenset[str]]] = self.__dict__.setdefault("_by_day", {})
        if signal not in cache:
            found: dict[date, set[str]] = defaultdict(set)
            if signal == "results_morning":
                for x, s in self.mornings:
                    found[x].add(s)
            else:
                source = {"bulk_buy": self.buys, "bulk_sell": self.sells}.get(signal)
                for s, days in (source if source is not None else self.promoters).items():
                    for x in days:
                        found[x].add(s)
            cache[signal] = {x: frozenset(v) for x, v in found.items()}
        return cache[signal]

    @cached_property
    def symbol_days(self) -> dict[str, tuple[list[date], dict[date, int]]]:
        out = {}
        for symbol, bars in self.panel.items():
            days = sorted(bars)
            out[symbol] = (days, {d: i for i, d in enumerate(days)})
        return out

    def extremes(self, n: int, *, high: bool) -> Mapping[str, frozenset[date]]:
        """{symbol: days whose close is at or beyond the extreme close of the n before it}."""
        cache: dict[tuple[int, bool], dict[str, frozenset[date]]] = self.__dict__.setdefault(
            "_extremes", {}
        )
        key = (n, high)
        if key not in cache:
            out: dict[str, frozenset[date]] = {}
            for symbol, (days, _) in self.symbol_days.items():
                bars = self.panel[symbol]
                closes = [bars[d].close if high else -bars[d].close for d in days]
                window: deque[int] = deque()
                hits = []
                for k, value in enumerate(closes):
                    while window and window[0] < k - n:
                        window.popleft()
                    if k >= n and value >= closes[window[0]]:
                        hits.append(days[k])
                    while window and closes[window[-1]] <= value:
                        window.pop()
                    window.append(k)
                out[symbol] = frozenset(hits)
            cache[key] = out
        return cache[key]

    @cached_property
    def value_ratios(self) -> dict[str, dict[date, float]]:
        out: dict[str, dict[date, float]] = {}
        for symbol, (days, _) in self.symbol_days.items():
            bars = self.panel[symbol]
            values = [bars[d].value for d in days]
            found = {}
            for k in range(du.VALUE_DAYS, len(days)):
                mean = statistics.fmean(values[k - du.VALUE_DAYS : k])
                if mean > 0:
                    found[days[k]] = values[k] / mean
            out[symbol] = found
        return out


class LiveData(Data):
    """The same data after the holdout end only, for a paper book (`deploy/engine_book.py`).

    Nothing on or before `since` is read, so a rule that needs history (a
    20-session mean, a 250-session high) trades nothing until that much has
    passed, as H-0065's book does.
    """

    def __init__(self, *, since: date, through: date) -> None:
        from datetime import timedelta

        from eulerlab.deploy import daily_books
        from eulerlab.ingest import trade_for_trade
        from eulerlab.intraday import nse_reports_screen as rep
        from eulerlab.intraday import other_data_screen as od

        trade_for_trade.build()
        self.end = through
        self.panel = du.load_panel(start=since + timedelta(days=1), end=through)
        self.sessions = sorted({d for bars in self.panel.values() for d in bars})
        self.index = {d: i for i, d in enumerate(self.sessions)}
        self.liquid = du.liquid_sets(self.panel, self.sessions)
        self.delivery = od.delivery_ratios(since=since)
        self.t2t = trade_for_trade.load()
        bulk = rep._parsed("bulk_deals", rep.bulk_net)
        self.buys, self.sells = rep.bulk_events(
            [(d, v) for d, v in bulk if d > since], self.sessions
        )
        self.results = daily_books.results_times(since=since, through=through)
        self.since = since

    @cached_property
    def promoters(self) -> Mapping[str, Mapping[date, float]]:
        from eulerlab.intraday import nse_reports_screen as rep

        sast = [x for _, found in rep._parsed("sast", rep.promoter_buys) for x in found]
        return rep.promoter_events([x for x in sast if x[1].date() > self.since], self.sessions)


# --- the engine -------------------------------------------------------------------------

Event = dm.Event


class Engine:
    def __init__(self, data: Data) -> None:
        self.data = data

    def value(self, s: Signal, symbol: str, day: date) -> float | None:
        """`s` for `symbol`, read `s.lag` sessions before `day` (the entry session)."""
        d = self.data
        at = d.prev(day, s.lag) if s.lag else day
        if at is None:
            return None
        v: float | None
        name = s.signal
        if name == "gap":
            v = dm._gap(d, symbol, at)
        elif name == "ret":
            v = self._ret(symbol, at, s.n)
        elif name == "day_return":
            bar = d.panel.get(symbol, {}).get(at)
            r = bar.close / bar.open - 1.0 if bar and bar.open > 0 else None
            v = r if r is not None and du.SPLIT_LOW <= 1 + r <= du.SPLIT_HIGH else None
        elif name == "delivery_ratio":
            v = d.delivery.get(symbol, {}).get(at)
        elif name == "value_ratio":
            v = d.value_ratios.get(symbol, {}).get(at)
        elif name in ("at_high", "at_low"):
            v = self._extreme(symbol, at, s.n, high=name == "at_high")
        elif name == "results_morning":
            v = 1.0 if (at, symbol) in d.mornings else None
        elif name == "bulk_buy":
            v = d.buys.get(symbol, {}).get(at)
        elif name == "bulk_sell":
            v = d.sells.get(symbol, {}).get(at)
        elif name == "promoter_buy":
            v = d.promoters.get(symbol, {}).get(at)
        else:  # pragma: no cover - the Literal type rules it out
            msg = f"unknown signal {name}"
            raise ValueError(msg)
        if v is not None and s.absolute:
            v = abs(v)
        return v

    def _ret(self, symbol: str, at: date, n: int) -> float | None:
        if n == 1:
            return self.data.ret(symbol, at)
        start = self.data.prev(at, n)
        bars = self.data.panel.get(symbol, {})
        if start is None or start not in bars or at not in bars or bars[start].close <= 0:
            return None
        i, j = self.data.index[start], self.data.index[at]
        window = self.data.sessions[i : j + 1]
        if any(x not in bars for x in window) or not du._clean(bars, window):
            return None
        return bars[at].close / bars[start].close - 1.0

    def _extreme(self, symbol: str, at: date, n: int, *, high: bool) -> float | None:
        return 1.0 if at in self.data.extremes(n, high=high).get(symbol, frozenset()) else None

    def _holds(self, c: Condition, symbol: str, day: date) -> bool:
        v = self.value(c, symbol, day)
        if v is None:
            return False
        if c.op is None or c.value is None:
            return True
        return {">=": v >= c.value, "<=": v <= c.value, ">": v > c.value, "<": v < c.value}[c.op]

    def _candidates(self, spec: RuleSpec, day: date) -> frozenset[str] | set[str]:
        """Stocks worth checking on `day`: an event signal narrows the list first."""
        liquid = self.data.liquid.get(day, frozenset())
        d = self.data
        for c in spec.when:
            at = d.prev(day, c.lag) if c.lag else day
            if at is None:
                return set()
            if c.signal in EVENT_SIGNALS:
                return d.by_day(c.signal).get(at, frozenset()) & liquid
        return liquid

    def events(self, spec: RuleSpec) -> list[Event]:
        d = self.data
        out: list[Event] = []
        first = spec.first
        for day in d.sessions:
            if not first <= day <= d.end or d.prev(day) is None:
                continue
            for symbol in sorted(self._candidates(spec, day)):
                if not d.tradable(symbol, day):
                    continue
                if not all(self._holds(c, symbol, day) for c in spec.when):
                    continue
                rank = self.value(spec.rank_by, symbol, day)
                if rank is None:
                    continue
                side = 1 if spec.side == "long" else -1
                if spec.side in ("against", "with") and spec.direction_of is not None:
                    sign = self.value(spec.direction_of, symbol, day)
                    if sign is None or sign == 0:
                        continue
                    side = (1 if sign > 0 else -1) * (1 if spec.side == "with" else -1)
                if spec.kind == "swing" and side < 0:
                    continue  # delivery is long only
                out.append((day, symbol, side, -rank if spec.rank_by.order == "desc" else rank))
        return out

    def window(self, spec: RuleSpec) -> list[date]:
        return [x for x in self.data.sessions if spec.first <= x <= self.data.end]

    def swings(self, spec: RuleSpec) -> list[Any]:
        """A swing rule's positions (`other_data_screen.Swing`), at most ten open."""
        return list(dm.swing_book(self.data, self.events(spec), spec.hold))

    def pieces(self, spec: RuleSpec) -> list[Any]:
        """The trades (intraday) or the daily pieces of each position (swing)."""
        events = self.events(spec)
        if spec.kind == "intraday":
            return list(dm.day_book(self.data, events))
        return [p for s in dm.swing_book(self.data, events, spec.hold) for p in s.pieces()]

    def screen(self, spec: RuleSpec) -> dict[str, Any]:
        """Research 176's screen figures plus the bias checks (`checks`)."""
        events = self.events(spec)
        window = self.window(spec)
        if spec.kind == "intraday":
            trades = dm.day_book(self.data, events)
            net = [(t.gross - t.costs) / t.notional * 1e4 for t in trades]
            gross = [t.gross / t.notional * 1e4 for t in trades]
            pieces: list[Any] = list(trades)
            count = len(trades)
            per = {
                "gross_mean": round(statistics.fmean(gross), 2) if gross else None,
                "net_mean": round(statistics.fmean(net), 2) if net else None,
            }
        else:
            swings = dm.swing_book(self.data, events, spec.hold)
            net = [(s.gross_total - sum(s.costs_at())) / s.notional * 1e4 for s in swings]
            pieces = [p for s in swings for p in s.pieces()]
            count = len(swings)
            per = {"net_mean": round(statistics.fmean(net), 2) if net else None}
        out: dict[str, Any] = {
            "kind": spec.kind,
            "rule": spec.describe(),
            "fingerprint": spec.fingerprint(),
            "first": spec.first.isoformat(),
            "count": count,
            "per_bps": per,
            **du._summary(pieces, window, dm.CAPITAL),
        }
        out["checks"] = checks(pieces, window, out)
        out["passes_screen"] = count > 0 and dm.passes(out)
        out["clean"] = out["passes_screen"] and not any(c["flag"] for c in out["checks"])
        return out


def daily(pieces: Sequence[Any], window: Sequence[date]) -> dict[date, float]:
    """Net return on the screen's capital for each session of `window` (0 with no trade)."""
    out = dict.fromkeys(window, 0.0)
    for p in pieces:
        if p.day in out:
            out[p.day] += (p.gross - p.costs) / dm.CAPITAL
    return out


# --- bias checks ------------------------------------------------------------------------


def checks(
    pieces: Sequence[Any], window: Sequence[date], summary: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """What the manual batches caught by hand, on every screen.

    Built in rather than checked: lookahead (the lag rules), today's lists used
    as history (the universe is each day's own top 500), trade-for-trade and
    BE/BZ stocks (skipped), a window chosen after the fact (it is the data's).
    Checked here, each with `flag` true when it fails:
    """
    out: list[dict[str, Any]] = []
    count = summary.get("count", 0)
    out.append(
        {
            "check": "enough trades",
            "value": count,
            "flag": count < MIN_TRADES,
            "why": f"under {MIN_TRADES} trades or positions (H-0172 fired 0 times)",
        }
    )
    base = (summary.get("net") or {}).get("sharpe")
    by_symbol: dict[str, float] = defaultdict(float)
    for p in pieces:
        by_symbol[p.symbol] += p.gross - p.costs
    best = {s for s, _ in sorted(by_symbol.items(), key=lambda x: -x[1])[:5]}
    rest = du._summary([p for p in pieces if p.symbol not in best], window, dm.CAPITAL)
    without = rest["net"]["sharpe"]
    kept = (without / base) if base and base > 0 and without is not None else None
    out.append(
        {
            "check": "not carried by five names",
            "value": round(kept, 3) if kept is not None else None,
            "flag": base is not None and base > 0 and (kept is None or kept < 0.5),
            "why": "Sharpe without the five most profitable stocks keeps under half",
        }
    )
    years = [y["sharpe"] for y in (summary.get("net_by_year") or {}).values()]
    years = [y for y in years if y is not None]
    share = sum(1 for y in years if y > 0) / len(years) if years else 0.0
    out.append(
        {
            "check": "positive in most years",
            "value": round(share, 3),
            "flag": share < 0.6,
            "why": "positive in under 60% of calendar years (the gate's own bar)",
        }
    )
    daily: dict[date, float] = defaultdict(float)
    for p in pieces:
        daily[p.day] += p.gross - p.costs
    total = sum(daily.values())
    top = sorted(daily.values(), reverse=True)[: max(1, len(window) // 100)]
    lucky = sum(top) / total if total > 0 else None
    out.append(
        {
            "check": "not a few lucky days",
            "value": round(lucky, 3) if lucky is not None else None,
            "flag": lucky is not None and lucky > 0.5,
            "why": "the best 1% of sessions make over half the net profit",
        }
    )
    thrice: dict[date, float] = defaultdict(float)
    for p in pieces:
        thrice[p.day] += (p.gross - 3 * p.costs) / dm.CAPITAL
    s3 = sc.daily_stats([thrice.get(d, 0.0) for d in window])["sharpe"]
    out.append(
        {
            "check": "survives 3x costs",
            "value": s3,
            "flag": False,
            "why": "information only: the gate tests 2x",
        }
    )
    return out


# --- cards ------------------------------------------------------------------------------


def _read_card_spec(path: Path) -> RuleSpec | None:
    raw = read_yaml(path) or {}
    block = raw.get("engine") if isinstance(raw, dict) else None
    return RuleSpec.model_validate(block) if isinstance(block, dict) else None


_CARD_SPECS = FileMemo(_read_card_spec, size=4096)


def card_spec(hypothesis: str, root: Path = HYPOTHESES) -> RuleSpec | None:
    """The `engine:` block of a card, or None when it has none.

    Kept per card until its file changes: the strategy list asks this once per
    row from several callers, 388 parses per request (2026-11-08). `RuleSpec`
    is frozen, so the shared value cannot be changed by a caller."""
    path = root / f"{hypothesis}.yaml"
    if not path.exists():
        return None
    return _CARD_SPECS(path)


def known_fingerprints(root: Path = HYPOTHESES) -> dict[str, str]:
    """{fingerprint: hypothesis} over every card with an engine block, and research 176's."""
    out = {spec.fingerprint(): h for h, spec in reference_specs().items()}
    for path in sorted(root.glob("H-*.yaml")):
        try:
            spec = card_spec(path.stem, root)
        except ValueError:
            continue
        if spec is not None:
            out.setdefault(spec.fingerprint(), path.stem)
    return out


def validation_run(hypothesis: str, data: Data | None = None) -> IntradayRun:
    """The trades the gate scores for an engine card (`validation.intraday.source`)."""
    from eulerlab.validation.intraday import IntradayRun

    spec = card_spec(hypothesis)
    if spec is None:
        msg = f"{hypothesis} has no engine block"
        raise KeyError(msg)
    engine = Engine(data or Data())
    return IntradayRun(engine.pieces(spec), [], engine.window(spec), dm.CAPITAL)
