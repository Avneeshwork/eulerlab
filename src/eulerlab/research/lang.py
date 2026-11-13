"""Strategy language v2: one typed expression language for three shapes of rule (ADR-175).

The card language of ADR-150 has eleven signals and one to five conditions.
Nightly batches now repeat earlier bets because the space is that small. Here
a rule is built from expressions over point-in-time fields:

    when:  and(ge(delay(abs(ret(3)), 1), 0.03), has(delay(results_morning, 1)))
    score: neutralize(rank(neg(delay(ret(5), 1))))

Three shapes, one spec:

    event          enter where `when` is true (today's engine, and every old card)
    cross_section  each `every`-th session, the `top` names by `score`
    minute         `MinuteSpec`: the first minute `entry` is true, filled at the
                   next minute's open, out at a fixed minute

Event and cross-section rules compile to the engine's own events and are
scored by its books and its costs (`rule_engine.Engine.screen`): there is no
second path to a number.

**Look-ahead does not compile.** Each field says how many sessions must pass
before it may be read (`min_lag`: 0 for what is known at the entry open, 1 for
what a session's close decides). `check_lookahead` adds up the `delay`s above
every field and refuses an expression that reads one early. A field's column
is laid out by knowledge time, by whoever builds the panel.

**Signal-only fields are never traded.** FII and DII flows and positions are
market-wide numbers a rule may condition on; the instrument traded is always
the cash stock.

The grammar and the tree are `features/formula.py`'s. Nothing is passed to
`exec` or `eval`.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from typing import Any, Literal, Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eulerlab.features.formula import FormulaError, Node, Op, parse, text_of
from eulerlab.features.formula import _walk as walk
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import daily_more_screen as dm
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import rule_engine

Matrix = NDArray[np.float64]

MAX_DEPTH = 12
MAX_NODES = 60
MAX_WINDOW = 260


class LookAhead(FormulaError):
    """The expression reads a field before it is known."""


@dataclass(frozen=True)
class FieldInfo:
    min_lag: int
    """Sessions that must pass before the value may be read: 0 or 1."""
    window: bool
    """True when the field takes a window, as `ret(5)`."""
    what: str
    market_wide: bool = False


FIELDS: dict[str, FieldInfo] = {
    name: FieldInfo(info.min_lag, name in ("ret", "at_high", "at_low"), info.what)
    for name, info in rule_engine.SIGNALS.items()
}
FIELDS.update(
    {
        "fii_net": FieldInfo(1, False, "FII net buying in cash, rupees crore", True),
        "dii_net": FieldInfo(1, False, "DII net buying in cash, rupees crore", True),
        "fii_futures_net": FieldInfo(1, False, "FII net index-futures contracts", True),
        "dii_futures_net": FieldInfo(1, False, "DII net index-futures contracts", True),
    }
)
"""Daily fields. The four market-wide ones are signals only (ADR-175)."""

MINUTE_FIELDS: dict[str, FieldInfo] = {
    name: FieldInfo(0, False, f"the minute bar's {name}")
    for name in ("open", "high", "low", "close", "volume")
}

_OPS: dict[str, Op] = {
    "neg": Op(1, 0, "minus x"),
    "abs": Op(1, 0, "absolute value"),
    "log": Op(1, 0, "natural log; missing when x <= 0"),
    "sign": Op(1, 0, "-1, 0 or 1"),
    "not": Op(1, 0, "1 where x is false or missing"),
    "has": Op(1, 0, "1 where x is present, else 0"),
    "add": Op(2, 0, "x + y"),
    "sub": Op(2, 0, "x - y"),
    "mul": Op(2, 0, "x * y"),
    "div": Op(2, 0, "x / y; missing when y is 0"),
    "gt": Op(2, 0, "1 where x > y"),
    "ge": Op(2, 0, "1 where x >= y"),
    "lt": Op(2, 0, "1 where x < y"),
    "le": Op(2, 0, "1 where x <= y"),
    "and": Op(2, 0, "1 where both are true"),
    "or": Op(2, 0, "1 where either is true"),
    "if": Op(3, 0, "if(c, x, y): x where c is true, else y"),
    "delay": Op(1, 1, "delay(x, n): x as it was n sessions earlier"),
    "delta": Op(1, 1, "delta(x, n): x minus x n sessions earlier"),
    "ts_mean": Op(1, 1, "mean over the last n sessions"),
    "ts_std": Op(1, 1, "sample standard deviation over the last n sessions"),
    "ts_sum": Op(1, 1, "sum over the last n sessions"),
    "ts_min": Op(1, 1, "minimum over the last n sessions"),
    "ts_max": Op(1, 1, "maximum over the last n sessions"),
    "ts_corr": Op(2, 1, "ts_corr(x, y, n): correlation of x and y over the last n sessions"),
    "rank": Op(1, 0, "the stock's place among that session's stocks, in (0, 1]"),
    "zscore": Op(1, 0, "x minus the session's mean, over the session's standard deviation"),
    "neutralize": Op(1, 0, "x minus the mean of the stock's sector that session"),
}
CROSS = frozenset({"rank", "zscore", "neutralize"})


def _table(fields: Mapping[str, FieldInfo]) -> dict[str, Op]:
    return {**_OPS, **{n: Op(0, 1 if f.window else 0, f.what) for n, f in fields.items()}}


OPS = _table(FIELDS)
MINUTE_OPS = {k: v for k, v in _table(MINUTE_FIELDS).items() if k not in CROSS}


def check_lookahead(node: Node, fields: Mapping[str, FieldInfo], delayed: int = 0) -> None:
    """Refuse an expression that reads any field before `min_lag` sessions have passed."""
    if node.op in fields:
        need = fields[node.op].min_lag
        if delayed < need:
            msg = (
                f"{node.op} is known only after its session closes: put it inside "
                f"delay(..., {need}) or more, not {delayed}"
            )
            raise LookAhead(msg)
        return
    more = node.params[0] if node.op == "delay" else 0
    for arg in node.args:
        check_lookahead(arg, fields, delayed + more)


def compile_text(text: str, *, minute: bool = False) -> Node:
    """Text to a checked tree, or `FormulaError` / `LookAhead`."""
    fields = MINUTE_FIELDS if minute else FIELDS
    node = parse(text, MINUTE_OPS if minute else OPS, max_depth=MAX_DEPTH, max_nodes=MAX_NODES)
    for n in walk(node):
        if any(not 1 <= p <= MAX_WINDOW for p in n.params):
            msg = f"{n.op} window is outside 1..{MAX_WINDOW}"
            raise FormulaError(msg)
    check_lookahead(node, fields)
    return node


def complexity(nodes: Sequence[Node]) -> dict[str, Any]:
    """Tree size, free numbers and fields used: what the search is charged for."""
    every = [n for node in nodes for n in walk(node)]
    names = {**FIELDS, **MINUTE_FIELDS}
    return {
        "size": len(every),
        "parameters": sum(1 for n in every if n.op == "const") + sum(len(n.params) for n in every),
        "fields": sorted({n.op for n in every if n.op in names}),
    }


# --- evaluation --------------------------------------------------------------------------


class Panel(Protocol):
    """Sessions down, stocks across. A missing value is NaN."""

    @property
    def days(self) -> Sequence[date]: ...
    @property
    def symbols(self) -> Sequence[str]: ...
    def field(self, name: str, n: int) -> Matrix: ...
    def groups(self) -> NDArray[np.int64]:
        """Each stock's sector as a number; -1 where it is not known."""
        ...


def _shift(x: Matrix, n: int) -> Matrix:
    out = np.full_like(x, np.nan)
    if n < len(x):
        out[n:] = x[: len(x) - n]
    return out


def _truth(x: Matrix) -> NDArray[np.bool_]:
    return np.nan_to_num(x, nan=0.0) > 0.5


def _rolling(x: Matrix, n: int, how: str) -> Matrix:
    """A window of n sessions ending today. Missing unless at least half are present."""
    need = max(1, math.ceil(n / 2))
    count = np.zeros_like(x)
    total = np.zeros_like(x)
    squares = np.zeros_like(x)
    low = np.full_like(x, np.inf)
    high = np.full_like(x, -np.inf)
    for k in range(n):
        s = _shift(x, k)
        ok = ~np.isnan(s)
        v = np.where(ok, s, 0.0)
        count += ok
        total += v
        squares += v * v
        low = np.where(ok, np.minimum(low, s), low)
        high = np.where(ok, np.maximum(high, s), high)
    with np.errstate(invalid="ignore", divide="ignore"):
        if how == "ts_sum":
            out = total
        elif how == "ts_mean":
            out = total / count
        elif how == "ts_min":
            out = low
        elif how == "ts_max":
            out = high
        else:
            var = (squares - total * total / count) / (count - 1)
            out = np.sqrt(np.maximum(var, 0.0))
            out = np.where(count >= 2, out, np.nan)
    return np.where(count >= need, out, np.nan)


def _corr(x: Matrix, y: Matrix, n: int) -> Matrix:
    need = max(3, math.ceil(n / 2))
    sums = [np.zeros_like(x) for _ in range(6)]
    for k in range(n):
        a, b = _shift(x, k), _shift(y, k)
        ok = ~(np.isnan(a) | np.isnan(b))
        a, b = np.where(ok, a, 0.0), np.where(ok, b, 0.0)
        for i, v in enumerate((ok.astype(np.float64), a, b, a * b, a * a, b * b)):
            sums[i] += v
    c, sa, sb, sab, saa, sbb = sums
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sab - sa * sb / c
        spread = np.sqrt((saa - sa * sa / c) * (sbb - sb * sb / c))
        out = cov / spread
    return np.where((c >= need) & (spread > 0), out, np.nan)


def _rank(x: Matrix) -> Matrix:
    out = np.full_like(x, np.nan)
    for t in range(len(x)):
        ok = ~np.isnan(x[t])
        k = int(ok.sum())
        if k:
            order = x[t, ok].argsort(kind="stable").argsort(kind="stable")
            out[t, ok] = (order + 1) / k
    return out


def _mean(x: Matrix) -> Matrix:
    """Each session's mean over the stocks present; NaN for a session with none."""
    ok = ~np.isnan(x)
    count = ok.sum(axis=1, keepdims=True)
    total = np.where(ok, x, 0.0).sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / count, np.nan)


def _zscore(x: Matrix) -> Matrix:
    ok = ~np.isnan(x)
    count = ok.sum(axis=1, keepdims=True)
    gap = np.where(ok, x - _mean(x), 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        std = np.sqrt((gap * gap).sum(axis=1, keepdims=True) / (count - 1))
        return np.where((count > 1) & (std > 0), (x - _mean(x)) / std, np.nan)


def _neutral(x: Matrix, groups: NDArray[np.int64]) -> Matrix:
    out = np.full_like(x, np.nan)
    for g in np.unique(groups):
        if g < 0:
            continue
        cols = groups == g
        out[:, cols] = x[:, cols] - _mean(x[:, cols])
    return out


class Evaluator:
    """Evaluates trees on one panel and keeps every subtree it has computed.

    A thousand candidates share most of their subtrees (`delay(ret(5), 1)`), so
    a batch costs little more than its distinct pieces.
    """

    def __init__(self, panel: Panel) -> None:
        self.panel = panel
        self._seen: dict[str, Matrix] = {}
        self.shape = (len(panel.days), len(panel.symbols))

    def value(self, node: Node) -> Matrix:
        key = text_of(node)
        if key not in self._seen:
            self._seen[key] = self._compute(node)
        return self._seen[key]

    def _compute(self, node: Node) -> Matrix:
        op = node.op
        if op == "const":
            return np.full(self.shape, float(node.value or 0.0))
        if not node.args:
            return self.panel.field(op, node.params[0] if node.params else 1)
        a = self.value(node.args[0])
        with np.errstate(invalid="ignore", divide="ignore"):
            if op == "neg":
                return -a
            if op == "abs":
                return np.abs(a)
            if op == "log":
                return np.where(a > 0, np.log(np.where(a > 0, a, 1.0)), np.nan)
            if op == "sign":
                return np.sign(a)
            if op == "not":
                return (~_truth(a)).astype(np.float64)
            if op == "has":
                return (~np.isnan(a)).astype(np.float64)
            if op == "delay":
                return _shift(a, node.params[0])
            if op == "delta":
                return a - _shift(a, node.params[0])
            if op in ("ts_mean", "ts_std", "ts_sum", "ts_min", "ts_max"):
                return _rolling(a, node.params[0], op)
            if op == "rank":
                return _rank(a)
            if op == "zscore":
                return _zscore(a)
            if op == "neutralize":
                return _neutral(a, self.panel.groups())
            b = self.value(node.args[1])
            if op == "ts_corr":
                return _corr(a, b, node.params[0])
            if op == "add":
                return a + b
            if op == "sub":
                return a - b
            if op == "mul":
                return a * b
            if op == "div":
                return np.where(b != 0, a / np.where(b != 0, b, 1.0), np.nan)
            if op in ("gt", "ge", "lt", "le"):
                found = {"gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]
                return found.astype(np.float64)
            if op == "and":
                return (_truth(a) & _truth(b)).astype(np.float64)
            if op == "or":
                return (_truth(a) | _truth(b)).astype(np.float64)
            if op == "if":
                return np.where(_truth(a), b, self.value(node.args[2]))
        msg = f"no rule to evaluate {op}"  # pragma: no cover - the table rules it out
        raise FormulaError(msg)


# --- the spec ----------------------------------------------------------------------------


class Spec(BaseModel):
    """An event or cross-section rule on daily data. Scored by `rule_engine`'s books."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shape: Literal["event", "cross_section"]
    kind: Literal["intraday", "swing"]
    hold: int = Field(0, ge=0, le=60)
    side: Literal["long", "short", "against", "with"] = "long"
    side_by: str | None = None
    """`against`/`with` trade against or with the sign of this expression."""
    when: str = "1"
    score: str
    """Higher is entered first."""
    top: int = Field(10, ge=1, le=10)
    every: int = Field(1, ge=1, le=20)
    first: date = rule_engine.FIRST

    @model_validator(mode="after")
    def _consistent(self) -> Spec:
        if self.kind == "swing" and not 2 <= self.hold <= 60:
            msg = "a swing rule holds 2 to 60 sessions"
            raise ValueError(msg)
        if self.kind == "intraday" and self.hold:
            msg = "an intraday rule closes the same session: hold must be 0"
            raise ValueError(msg)
        if self.kind == "swing" and self.side == "short":
            msg = "swing rules are delivery, long only (no overnight cash shorts)"
            raise ValueError(msg)
        if self.side in ("against", "with") and self.side_by is None:
            msg = f"side {self.side} needs side_by"
            raise ValueError(msg)
        self.trees  # noqa: B018  (compiles every expression, or raises)
        return self

    @cached_property
    def trees(self) -> dict[str, Node]:
        out = {"when": compile_text(self.when), "score": compile_text(self.score)}
        if self.side_by is not None:
            out["side_by"] = compile_text(self.side_by)
        return out

    @property
    def complexity(self) -> dict[str, Any]:
        return complexity(list(self.trees.values()))

    def fingerprint(self) -> str:
        body = self.model_dump(mode="json")
        for key, tree in self.trees.items():
            body[key] = text_of(tree)
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]

    def describe(self) -> str:
        hold = "open to close" if self.kind == "intraday" else f"hold {self.hold} sessions"
        pick = (
            f"when {text_of(self.trees['when'])}"
            if self.shape == "event"
            else f"top {self.top} every {self.every} session(s)"
        )
        return f"{self.kind}: {pick}; {self.side}; {hold}; best {text_of(self.trees['score'])}"


def _leaf(s: rule_engine.Signal) -> Node:
    node = Node(op=s.signal, params=(s.n,) if FIELDS[s.signal].window else ())
    if s.absolute:
        node = Node(op="abs", args=(node,))
    return Node(op="delay", args=(node,), params=(s.lag,)) if s.lag else node


def from_rule(rule: rule_engine.RuleSpec) -> Spec:
    """An ADR-150 card as a v2 spec that makes the same events."""
    terms: list[Node] = []
    for c in rule.when:
        leaf = _leaf(c)
        if c.op is None or c.value is None:
            terms.append(Node(op="has", args=(leaf,)))
        else:
            name = {">=": "ge", "<=": "le", ">": "gt", "<": "lt"}[c.op]
            terms.append(Node(op=name, args=(leaf, Node(op="const", value=float(c.value)))))
    when = terms[0]
    for term in terms[1:]:
        when = Node(op="and", args=(when, term))
    score = _leaf(rule.rank_by)
    if rule.rank_by.order == "asc":
        score = Node(op="neg", args=(score,))
    return Spec.model_construct(
        shape="event",
        kind=rule.kind,
        hold=rule.hold,
        side=rule.side,
        side_by=text_of(_leaf(rule.direction_of)) if rule.direction_of is not None else None,
        when=text_of(when),
        score=text_of(score),
        top=10,
        every=1,
        first=rule.first,
    )


def events(
    spec: Spec,
    ev: Evaluator,
    tradable: NDArray[np.bool_],
    ok_day: NDArray[np.bool_],
) -> list[rule_engine.Event]:
    """The spec's entries, in the engine's order: by session, then by symbol."""
    trees = spec.trees
    score = ev.value(trees["score"])
    mask = tradable & ok_day[:, None] & _truth(ev.value(trees["when"])) & ~np.isnan(score)
    side = np.full(ev.shape, 1.0 if spec.side in ("long", "with", "against") else -1.0)
    if spec.side in ("against", "with"):
        sign = np.sign(np.nan_to_num(ev.value(trees["side_by"]), nan=0.0))
        side = sign if spec.side == "with" else -sign
        mask &= side != 0
    if spec.kind == "swing":
        mask &= side > 0
    days, symbols = ev.panel.days, ev.panel.symbols
    order = np.argsort(np.array(symbols), kind="stable")
    out: list[rule_engine.Event] = []
    turn = 0
    for t in (int(i) for i in np.flatnonzero(ok_day)):
        if days[t] < spec.first:
            continue
        turn += 1
        if spec.shape == "cross_section" and (turn - 1) % spec.every:
            continue
        cols = [int(j) for j in order if mask[t, j]]
        if spec.shape == "cross_section":
            cols = sorted(cols, key=lambda j: -score[t, j])[: spec.top]
            cols.sort(key=lambda j: symbols[j])
        out.extend((days[t], symbols[j], int(side[t, j]), float(-score[t, j])) for j in cols)
    return out


# --- minute rules ------------------------------------------------------------------------


class MinuteSpec(BaseModel):
    """An intraday rule on one stock's minute bars: in after `entry` turns true, out at `exit_at`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: str
    side: Literal["long", "short"]
    start: int = Field(5, ge=1, le=300)
    """First minute after 09:15 the rule may see."""
    exit_at: int = Field(355, ge=10, le=374)

    @model_validator(mode="after")
    def _compiles(self) -> MinuteSpec:
        compile_text(self.entry, minute=True)
        if self.exit_at <= self.start + 1:
            msg = "exit_at must come after the first minute a fill can happen"
            raise ValueError(msg)
        return self

    def fingerprint(self) -> str:
        body = {
            **self.model_dump(mode="json"),
            "entry": text_of(compile_text(self.entry, minute=True)),
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


class _Bars:
    """One session of one stock as a panel: minutes down, one column."""

    def __init__(self, columns: Mapping[str, Sequence[float | None]]) -> None:
        self._columns = {
            k: np.array([np.nan if v is None else v for v in col], dtype=np.float64)[:, None]
            for k, col in columns.items()
        }
        self.days: Sequence[date] = [date.min] * len(next(iter(self._columns.values())))
        self.symbols: Sequence[str] = [""]

    def field(self, name: str, n: int) -> Matrix:
        return self._columns[name]

    def groups(self) -> NDArray[np.int64]:
        return np.array([-1])


def minute_entry(spec: MinuteSpec, columns: Mapping[str, Sequence[float | None]]) -> int | None:
    """The minute to fill at: the one after `entry` first turns true, or None.

    The bar that turns the rule true is finished before the fill, so the fill
    cannot have been seen by the rule.
    """
    truth = _truth(Evaluator(_Bars(columns)).value(compile_text(spec.entry, minute=True)))[:, 0]
    for m in range(spec.start, min(spec.exit_at - 1, len(truth))):
        if truth[m]:
            return m + 1
    return None


def minute_trade(
    spec: MinuteSpec, symbol: str, day: ip.Day, notional: float = dm.TRADE
) -> cs.Trade | None:
    """The rule's one trade in this session, with the costs every minute screen pays."""
    columns = {
        "open": day.open_,
        "high": day.high,
        "low": day.low,
        "close": day.close,
        "volume": day.volume,
    }
    at = minute_entry(spec, columns)
    if at is None:
        return None
    filled, left = day.fill_at(at), day.fill_at(spec.exit_at)
    if filled is None or left is None or filled[0] >= left[0]:
        return None
    quantity = cs.sized(notional, filled[1])
    if not quantity or filled[1] < cs.MIN_PRICE:
        return None
    direction = 1 if spec.side == "long" else -1
    return cs.Trade(
        symbol, day.day, direction, quantity, filled[0], filled[1], left[0], left[1], "time"
    )


def describe() -> str:
    """The language, for a prompt: fields with their earliest lag, then operators."""
    lines = ["Fields (lag = sessions that must pass before it may be read):"]
    lines += [
        f"  {n}{'(n)' if f.window else ''}  lag >= {f.min_lag}  {f.what}"
        + ("  [market-wide, signal only]" if f.market_wide else "")
        for n, f in FIELDS.items()
    ]
    lines.append("Operators:")
    lines += [f"  {n}  {o.doc}" for n, o in _OPS.items()]
    return "\n".join(lines)
