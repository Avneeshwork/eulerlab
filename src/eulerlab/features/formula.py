"""A small formula language for features, so an agent can compose a signal without writing Python.

    neg(ts_mad(ret(1), 62))          the library's low_volatility, as a formula
    div(close, ts_max(close, 252))   the library's price_to_52w_high

**It is parsed and interpreted. Nothing is ever passed to `exec` or `eval`.**
`research/codegen.py` explains why generated source is refused: it would break
the lookahead firewall and have no tests behind it. A formula is a tree of
operators that are each written and tested here, so it keeps both guarantees
and is still reviewable and diffable (ADR-096).

**Every operator looks back, never forward.** A formula is a pure function of
one symbol's history ending at the evaluation date, exactly like a library
`Feature`, and `compile_formula` returns a `Feature`. So the IC screen,
`RankAndHold`, codegen and the critic take a formula wherever they take a
library name, through `resolve`. Ranking across stocks stays in the strategy.

**What it cannot do:** read anything but close, volume and turnover; compare
stocks with each other; or use fundamentals. Those need new, tested inputs.

Edge rule. A window operator needs at least half its window present. The ten
hand-written features have their own minimum counts (20 of 62, 3 of 5, ...),
so a formula and the feature it copies agree exactly on full histories and can
differ only when most of a window is missing. `tests/test_features_formula.py`
pins the agreement.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from eulerlab.features.library import BY_NAME, Feature
from eulerlab.features.panel import PanelRow
from eulerlab.quality.robust import median

PREFIX = "formula:"
"""A card's `feature:` that starts with this is a formula, not a library name."""

MAX_DEPTH = 6
MAX_NODES = 24
MAX_WINDOW = 504
"""Two years of sessions. Longer windows leave too little of a 2015 panel to test on."""

Value = float | None


class FormulaError(ValueError):
    """The text is not a formula this language accepts. Raised, never skipped."""


class Node(BaseModel):
    """One operator, its argument nodes and its integer parameters (window, lag)."""

    model_config = ConfigDict(frozen=True)

    op: str
    args: tuple[Node, ...] = ()
    params: tuple[int, ...] = ()
    value: float | None = None
    """Only for `const`."""


@dataclass(frozen=True)
class Op:
    args: int
    params: int
    doc: str


INPUTS = ("close", "volume", "turnover")
"""Each reads as missing (None) when it is zero or negative: a zero close is no price."""

OPS: dict[str, Op] = {
    "close": Op(0, 0, "the raw close on the day"),
    "volume": Op(0, 0, "shares traded on the day"),
    "turnover": Op(0, 0, "rupees traded on the day"),
    "ret": Op(0, 1, "ret(n): close over close n sessions earlier, minus 1"),
    "delay": Op(1, 1, "delay(x, n): x as it was n sessions earlier"),
    "delta": Op(1, 1, "delta(x, n): x minus x n sessions earlier"),
    "neg": Op(1, 0, "minus x"),
    "abs": Op(1, 0, "absolute value"),
    "log": Op(1, 0, "natural log; missing when x <= 0"),
    "sign": Op(1, 0, "-1, 0 or 1"),
    "add": Op(2, 0, "x + y"),
    "sub": Op(2, 0, "x - y"),
    "mul": Op(2, 0, "x * y"),
    "div": Op(2, 0, "x / y; missing when y is 0"),
    "ts_mean": Op(1, 1, "mean over the last n sessions"),
    "ts_std": Op(1, 1, "sample standard deviation over the last n sessions"),
    "ts_sum": Op(1, 1, "sum over the last n sessions"),
    "ts_min": Op(1, 1, "minimum over the last n sessions"),
    "ts_max": Op(1, 1, "maximum over the last n sessions"),
    "ts_median": Op(1, 1, "median over the last n sessions"),
    "ts_mad": Op(1, 1, "median absolute deviation from the median, last n sessions"),
    "ts_rank": Op(1, 1, "share of the last n values at or below today's, in (0, 1]"),
    "ts_drawdown": Op(1, 1, "worst fall from a running peak over the last n sessions, <= 0"),
}

# --- parsing ---

_TOKEN = re.compile(r"\s*(?:(?P<num>-?\d+(?:\.\d+)?)|(?P<name>[a-z_][a-z0-9_]*)|(?P<sym>[(),]))")


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            msg = f"cannot read {text[pos:]!r}"
            raise FormulaError(msg)
        out.append(m.group("num") or m.group("name") or m.group("sym"))
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return out


def _is_number(token: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", token))


def parse(text: str) -> Node:
    """Text to a checked tree. Refuses unknown operators, wrong arity, bad windows, oversize."""
    tokens = _tokens(text.removeprefix(PREFIX))
    if not tokens:
        msg = "empty formula"
        raise FormulaError(msg)
    node, used = _expr(tokens, 0)
    if used != len(tokens):
        msg = f"unexpected {' '.join(tokens[used:])!r} after the formula"
        raise FormulaError(msg)
    check(node)
    return node


def _expr(tokens: list[str], i: int) -> tuple[Node, int]:
    token = tokens[i]
    if _is_number(token):
        return Node(op="const", value=float(token)), i + 1
    if token not in OPS:
        msg = f"unknown operator {token!r}; the language has {sorted(OPS)}"
        raise FormulaError(msg)
    spec = OPS[token]
    if spec.args == 0 and spec.params == 0:
        return Node(op=token), i + 1
    if i + 1 >= len(tokens) or tokens[i + 1] != "(":
        msg = f"{token} needs arguments in brackets"
        raise FormulaError(msg)
    i += 2
    items: list[Node] = []
    while True:
        if i >= len(tokens):
            msg = f"{token}( is never closed"
            raise FormulaError(msg)
        item, i = _expr(tokens, i)
        items.append(item)
        if i < len(tokens) and tokens[i] == ",":
            i += 1
            continue
        if i < len(tokens) and tokens[i] == ")":
            i += 1
            break
        msg = f"expected ',' or ')' in {token}("
        raise FormulaError(msg)
    if len(items) != spec.args + spec.params:
        msg = f"{token} takes {spec.args + spec.params} arguments, got {len(items)}"
        raise FormulaError(msg)
    args = tuple(items[: spec.args])
    params: list[int] = []
    for p in items[spec.args :]:
        if p.op != "const" or p.value is None or not p.value.is_integer():
            msg = f"{token}'s window or lag must be a whole number, got {text_of(p)}"
            raise FormulaError(msg)
        params.append(int(p.value))
    return Node(op=token, args=args, params=tuple(params)), i


def check(node: Node) -> None:
    """The limits an agent's formula must respect."""
    if depth(node) > MAX_DEPTH:
        msg = f"depth {depth(node)} exceeds {MAX_DEPTH}"
        raise FormulaError(msg)
    if size(node) > MAX_NODES:
        msg = f"{size(node)} operators exceed {MAX_NODES}"
        raise FormulaError(msg)
    for n in _walk(node):
        for p in n.params:
            if not 1 <= p <= MAX_WINDOW:
                msg = f"{n.op} window {p} is outside 1..{MAX_WINDOW}"
                raise FormulaError(msg)


def _walk(node: Node) -> list[Node]:
    out = [node]
    for a in node.args:
        out.extend(_walk(a))
    return out


def depth(node: Node) -> int:
    return 1 + max((depth(a) for a in node.args), default=0)


def size(node: Node) -> int:
    return len(_walk(node))


def text_of(node: Node) -> str:
    """The canonical text. `parse(text_of(n)) == n`."""
    if node.op == "const":
        v = node.value if node.value is not None else 0.0
        return str(int(v)) if v.is_integer() else repr(v)
    if not node.args and not node.params:
        return node.op
    inner = [text_of(a) for a in node.args] + [str(p) for p in node.params]
    return f"{node.op}({', '.join(inner)})"


def lookback(node: Node) -> int:
    """Rows of history the formula needs to produce today's value."""
    if node.op == "const" or node.op in INPUTS:
        return 1
    if node.op == "ret":
        return node.params[0] + 1
    if node.op in ("delay", "delta"):
        return lookback(node.args[0]) + node.params[0]
    if node.op.startswith("ts_"):
        return lookback(node.args[0]) + node.params[0] - 1
    return max(lookback(a) for a in node.args)


# --- evaluation ---


def _positive(v: float) -> Value:
    return v if v > 0 else None


def _min_present(n: int) -> int:
    return max(1, math.ceil(n / 2))


def _window(fn: Callable[[list[float]], Value], n: int) -> Callable[[list[Value]], Value]:
    def apply(values: list[Value]) -> Value:
        present = [v for v in values if v is not None]
        return fn(present) if len(present) >= _min_present(n) else None

    return apply


def _mad(values: list[float]) -> Value:
    centre = median(values)
    return median([abs(v - centre) for v in values])


def _rank(values: list[float]) -> Value:
    last = values[-1]
    return sum(1 for v in values if v <= last) / len(values)


def _drawdown(values: list[float]) -> Value:
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def _std(values: list[float]) -> Value:
    return statistics.stdev(values) if len(values) >= 2 else None


WINDOW_FNS: dict[str, Callable[[list[float]], Value]] = {
    "ts_mean": lambda xs: math.fsum(xs) / len(xs),
    "ts_std": _std,
    "ts_sum": math.fsum,
    "ts_min": min,
    "ts_max": max,
    "ts_median": median,
    "ts_mad": _mad,
    "ts_rank": _rank,
    "ts_drawdown": _drawdown,
}


def _unary(op: str, x: float) -> Value:
    if op == "neg":
        return -x
    if op == "abs":
        return abs(x)
    if op == "log":
        return math.log(x) if x > 0 else None
    return float((x > 0) - (x < 0))  # sign


def _binary(op: str, x: float, y: float) -> Value:
    if op == "add":
        return x + y
    if op == "sub":
        return x - y
    if op == "mul":
        return x * y
    return x / y if y != 0 else None  # div


def series(node: Node, rows: Sequence[PanelRow], k: int) -> list[Value]:
    """The formula's values at the last `k` rows, oldest first; None before the data starts.

    Each operator asks its arguments only for the positions it needs, so a
    window of 63 over a window of 62 costs about 125 values, not the whole panel.
    Position j depends on rows up to j and never beyond: that is the lookahead
    guarantee, and `test_no_value_depends_on_a_later_row` checks it directly.
    """
    n = len(rows)
    first = n - k

    def row(j: int) -> PanelRow | None:
        return rows[first + j] if 0 <= first + j < n else None

    if node.op == "const":
        return [node.value] * k
    if node.op in INPUTS:
        out: list[Value] = []
        for j in range(k):
            r = row(j)
            out.append(None if r is None else _positive(float(getattr(r, node.op))))
        return out
    if node.op == "ret":
        lag = node.params[0]
        out = []
        for j in range(k):
            now, then = row(j), row(j - lag)
            if now is None or then is None or now.close <= 0 or then.close <= 0:
                out.append(None)
            else:
                out.append(now.close / then.close - 1.0)
        return out
    if node.op in ("delay", "delta"):
        lag = node.params[0]
        child = series(node.args[0], rows, k + lag)
        past = child[:k]
        if node.op == "delay":
            return past
        current = child[lag:]
        return [
            c - p if c is not None and p is not None else None
            for c, p in zip(current, past, strict=True)
        ]
    if node.op in WINDOW_FNS:
        width = node.params[0]
        child = series(node.args[0], rows, k + width - 1)
        apply = _window(WINDOW_FNS[node.op], width)
        return [apply(child[j : j + width]) for j in range(k)]
    if len(node.args) == 1:
        return [None if x is None else _unary(node.op, x) for x in series(node.args[0], rows, k)]
    left = series(node.args[0], rows, k)
    right = series(node.args[1], rows, k)
    return [
        None if x is None or y is None else _binary(node.op, x, y)
        for x, y in zip(left, right, strict=True)
    ]


def value(node: Node, history: Sequence[PanelRow]) -> Value:
    """Today's value: the last row of `history` is the evaluation date."""
    if not history:
        return None
    result = series(node, history[-lookback(node) :], 1)[0]
    return result if result is not None and math.isfinite(result) else None


def compile_formula(text: str, *, name: str | None = None, min_history: int = 0) -> Feature:
    """A formula as a library `Feature`, usable wherever a feature is.

    `min_history` defaults to the formula's lookback. The zoo passes each
    library feature's own minimum instead, which can be shorter (the 52-week
    high starts at 200 rows); a window with too little data then reads as
    missing under the edge rule rather than as a smaller number.
    """
    node = parse(text)
    canonical = text_of(node)

    def fn(history: Sequence[PanelRow]) -> Value:
        return value(node, history)

    return Feature(
        name or PREFIX + canonical,
        fn,
        f"formula {canonical}",
        min_history or lookback(node),
    )


def resolve(name: str) -> Feature:
    """A card's `feature:` value: a library name, or `formula:<text>`. Raises KeyError otherwise."""
    if name.startswith(PREFIX):
        try:
            return compile_formula(name)
        except FormulaError as err:
            raise KeyError(f"{name!r}: {err}") from err
    return BY_NAME[name]


def is_known(name: str) -> bool:
    try:
        resolve(name)
    except KeyError:
        return False
    return True


# --- originality ---


def _subtrees(node: Node) -> dict[str, int]:
    """Every subtree's canonical text and its size. Constants alone are not counted."""
    out: dict[str, int] = {}
    for n in _walk(node):
        if n.op != "const":
            out[text_of(n)] = size(n)
    return out


def similarity(candidate: Node, other: Node) -> float:
    """Size of the largest subtree the two share exactly, over the candidate's size.

    1.0 means the candidate is wholly contained in `other`; a lone `close`
    shared by everything scores 1 / size. AlphaAgent (research 130) uses the
    largest common subtree; this is the exact-match version of it.
    """
    mine = _subtrees(candidate)
    theirs = _subtrees(other)
    shared = [s for t, s in mine.items() if t in theirs]
    return max(shared, default=0) / size(candidate)


def max_similarity(candidate: Node, others: Sequence[Node]) -> float:
    return max((similarity(candidate, o) for o in others), default=0.0)


# --- the alpha zoo ---


@dataclass(frozen=True)
class ZooEntry:
    name: str
    text: str
    min_history: int
    """The library feature's own minimum, kept so the two refuse the same short histories."""


ZOO: tuple[ZooEntry, ...] = (
    ZooEntry("momentum_12_1", "delay(ret(231), 21)", 253),
    ZooEntry("momentum_6_1", "delay(ret(105), 21)", 148),
    ZooEntry("reversal_1m", "neg(ret(21))", 22),
    ZooEntry("low_volatility", "neg(ts_mad(ret(1), 62))", 63),
    ZooEntry("max_drawdown", "ts_drawdown(close, 126)", 126),
    ZooEntry("turnover_liquidity", "log(ts_median(turnover, 63))", 63),
    ZooEntry("illiquidity_amihud", "neg(ts_median(div(abs(ret(1)), turnover), 62))", 63),
    ZooEntry("small_size", "neg(log(close))", 1),
    ZooEntry("price_to_52w_high", "div(close, ts_max(close, 252))", 200),
    ZooEntry("volume_trend", "div(ts_median(volume, 5), ts_median(volume, 63))", 63),
)
"""The ten library features, rewritten. The originality check compares new ideas against these."""


def zoo_nodes() -> list[Node]:
    return [parse(e.text) for e in ZOO]


def zoo_features() -> list[Feature]:
    return [compile_formula(e.text, name=e.name, min_history=e.min_history) for e in ZOO]


def describe() -> str:
    """The operator list, for a model's prompt or a person."""
    lines = [f"  {name:<12} {op.doc}" for name, op in OPS.items()]
    return "operators:\n" + "\n".join(lines)
