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

import copy
import hashlib
import json
import statistics
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

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


class Rule(Protocol):
    """What a screen needs of a rule: this module's `RuleSpec`, or `research/lang.py`'s `Spec`."""

    @property
    def kind(self) -> Literal["intraday", "swing"]: ...
    @property
    def hold(self) -> int: ...
    @property
    def first(self) -> date: ...
    def fingerprint(self) -> str: ...
    def describe(self) -> str: ...


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


def through(data: Data, end: date) -> Data:
    """`data` with every session after `end` dropped; `data` itself is not changed (#152).

    Cutting only the entry window would still let a swing entered in December
    2023 exit on a 2024 price, so the panel itself stops at `end`. Lazily built
    tables are dropped from the copy, so none of them was computed on the
    sessions cut away, except promoter buys, which are dated events and are cut
    by date. Delivery, deals and results after `end` stay, but no rule can
    trade on them: a day with no bar is not tradable.
    """
    cut = copy.copy(data)
    lazy = [k for k in vars(cut) if isinstance(getattr(type(cut), k, None), cached_property)]
    for name in lazy:
        del cut.__dict__[name]
    if "promoters" in vars(data):
        cut.__dict__["promoters"] = {
            s: {d: v for d, v in m.items() if d <= end} for s, m in data.promoters.items()
        }
    cut.panel = {s: {d: b for d, b in bars.items() if d <= end} for s, bars in data.panel.items()}
    cut.sessions = [d for d in data.sessions if d <= end]
    cut.index = {d: i for i, d in enumerate(cut.sessions)}
    cut.end = min(data.end, end)
    return cut


def as_of_open(data: Data, day: date) -> Data:
    """`data` as it stood at `day`'s official open: a look-ahead test (ADR-200).

    Every session after `day` is gone; `day`'s own bar keeps its open and loses
    its close and traded value (NaN); delivery, trade-for-trade lists and
    results disclosed on or after `day`'s 09:15 are gone; bulk-deal and promoter
    events keep only those dated on or before `day` (each is dated by the
    session after its disclosure). The liquid universe is rebuilt from the cut
    panel. A rule's entries for `day` must be the same on this as on `data`.
    """
    from datetime import datetime, time

    nan = float("nan")
    cut = object.__new__(Data)
    cut.end = day
    cut.panel = {
        s: {d: (b if d < day else du.Bar(b.open, nan, nan)) for d, b in bars.items() if d <= day}
        for s, bars in data.panel.items()
    }
    cut.panel = {s: bars for s, bars in cut.panel.items() if bars}
    cut.sessions = [d for d in data.sessions if d <= day]
    cut.index = {d: i for i, d in enumerate(cut.sessions)}
    cut.liquid = du.liquid_sets(cut.panel, cut.sessions)
    cut.delivery = {s: {d: v for d, v in m.items() if d < day} for s, m in data.delivery.items()}
    cut.t2t = {d: v for d, v in data.t2t.items() if d < day}
    cut.buys = {s: {d: v for d, v in m.items() if d <= day} for s, m in data.buys.items()}
    cut.sells = {s: {d: v for d, v in m.items() if d <= day} for s, m in data.sells.items()}
    opening = datetime.combine(day, time(9, 15))
    cut.results = {
        s: [t for t in times if t.replace(tzinfo=None) < opening]
        for s, times in data.results.items()
    }
    cut.__dict__["promoters"] = {
        s: {d: v for d, v in m.items() if d <= day} for s, m in data.promoters.items()
    }
    return cut


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
        # ETFs and fund units (INF ISINs) are never traded by a paper or live book: their
        # official opening print is often stale (research 180, HISTORY #87). The research
        # window (`Data`) keeps them, so research 176's reproduction is unchanged.
        funds = du.fund_symbols()
        self.liquid = {
            d: frozenset(s for s in names if s not in funds)
            for d, names in du.liquid_sets(self.panel, self.sessions).items()
        }
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
    def __init__(self, data: Data, prices: dm.Pricer | None = None) -> None:
        self.data = data
        self.prices = prices
        """A fill-price model (`intraday/fill_price.PriceModel`, #119); None fills at the
        official open and close with 2 bps a side, as research 176 did."""
        self.returns: dict[str, dict[date, float]] = {}
        """Daily net returns of each rule screened, by fingerprint."""

    @cached_property
    def short(self) -> frozenset[date]:
        """Short sessions (Muhurat, a late open): no entry on them (ADR-157).
        An open-to-close trade there is an hour long and a thin print."""
        from eulerlab.master.sessions import short_days

        totals: dict[date, float] = defaultdict(float)
        for bars in self.data.panel.values():
            for day, bar in bars.items():
                totals[day] += bar.value
        return short_days(totals)

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

    def events(self, spec: Rule) -> list[Event]:
        if not isinstance(spec, RuleSpec):
            # A language-v2 rule: its entries come from the tables (ADR-175).
            from eulerlab.research import fast_eval

            return fast_eval.events_for(self, spec)
        d = self.data
        out: list[Event] = []
        first = spec.first
        for day in d.sessions:
            if not first <= day <= d.end or d.prev(day) is None or day in self.short:
                continue
            out.extend(self.events_on(spec, day))
        return out

    def events_on(self, spec: RuleSpec, day: date) -> list[Event]:
        """The entries one session's open produces (no window check): `events` per day."""
        d = self.data
        out: list[Event] = []
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

    def window(self, spec: Rule) -> list[date]:
        return [x for x in self.data.sessions if spec.first <= x <= self.data.end]

    def swings(self, spec: Rule) -> list[Any]:
        """A swing rule's positions (`other_data_screen.Swing`), at most ten open."""
        return list(dm.swing_book(self.data, self.events(spec), spec.hold, self.prices))

    def pieces(self, spec: Rule) -> list[Any]:
        """The trades (intraday) or the daily pieces of each position (swing)."""
        events = self.events(spec)
        if spec.kind == "intraday":
            return list(dm.day_book(self.data, events, self.prices))
        return [
            p for s in dm.swing_book(self.data, events, spec.hold, self.prices) for p in s.pieces()
        ]

    def screen(self, spec: Rule, events: Sequence[Event] | None = None) -> dict[str, Any]:
        """Research 176's screen figures plus the bias checks (`checks`).

        `events` replaces the rule's own entries: the robustness battery's half
        universes and shifted-date placebos (#158) are screened this way. Every
        delivery sell pays the DP charge (#153); the paper books, which build
        their positions without `screen`, do not yet (T-4633)."""
        from eulerlab.costs import router

        with router.dp_charges():
            return self._screen(spec, events)

    def _screen(self, spec: Rule, events: Sequence[Event] | None) -> dict[str, Any]:
        events = self.events(spec) if events is None else list(events)
        window = self.window(spec)
        if spec.kind == "intraday":
            trades = dm.day_book(self.data, events, self.prices)
            net = [(t.gross - t.costs) / t.notional * 1e4 for t in trades]
            gross = [t.gross / t.notional * 1e4 for t in trades]
            pieces: list[Any] = list(trades)
            count = len(trades)
            per = {
                "gross_mean": round(statistics.fmean(gross), 2) if gross else None,
                "net_mean": round(statistics.fmean(net), 2) if net else None,
            }
        else:
            swings = dm.swing_book(self.data, events, spec.hold, self.prices)
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
        if self.prices is not None:  # every modelled screen says how it priced its fills
            describe = getattr(self.prices, "describe", None)
            out["price_model"] = describe() if callable(describe) else "a custom pricer"
        out["checks"] = checks(pieces, window, out)
        out["passes_screen"] = count > 0 and dm.passes(out)
        out["clean"] = out["passes_screen"] and not any(c["flag"] for c in out["checks"])
        # Kept for the experiment store (ADR-172): the caller takes it by fingerprint.
        self.returns[spec.fingerprint()] = daily(pieces, window)
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


def _read_card_spec(path: Path) -> Rule | None:
    raw = read_yaml(path) or {}
    block = raw.get("engine") if isinstance(raw, dict) else None
    if isinstance(block, dict):
        return RuleSpec.model_validate(block)
    v2 = raw.get("engine_v2") if isinstance(raw, dict) else None
    if isinstance(v2, dict):
        # A language-v2 rule (ADR-175): same screen, books and gate path.
        from eulerlab.research import lang

        return lang.Spec.model_validate(v2)
    return None


_CARD_SPECS = FileMemo(_read_card_spec, size=4096)


def card_spec(hypothesis: str, root: Path = HYPOTHESES) -> Rule | None:
    """The `engine:` (or `engine_v2:`) block of a card, or None when it has neither.

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
    from eulerlab.costs import router

    engine = Engine(data or Data())
    with router.dp_charges():  # a swing card's delivery sells pay DP at the gate too (#153)
        pieces = engine.pieces(spec)
    return IntradayRun(pieces, [], engine.window(spec), dm.CAPITAL)
