"""Running a strategy someone typed, without giving away the firewall.

ADR-027 refused to execute generated Python, and the reason still stands: a
`Strategy` is safe from lookahead because it receives a `MarketView` containing
only history up to its decision date, and **arbitrary code can ignore that and
open the panel file directly.** The firewall is structural precisely so nothing
has to remember to respect it, and a bare `exec` is the one thing that undoes
it.

This module is how you get "paste a strategy and backtest it" without that.
The trick is that the danger was never *executing code* — it was executing code
with **reach**. Take away every route out of the function and what remains can
only do arithmetic on the view it was handed, which is exactly the property the
firewall needs.

Three layers, each of which alone would be insufficient:

1. **An allowlisted AST.** `import`, `with`, `try`, `global`, `class`,
   decorators, `while`, `del`, `yield` and `async` are rejected before the code
   is ever compiled. Anything not on the list is rejected too — the default is
   no.
2. **Allowlisted attribute names.** Not merely "no dunders". A name has to be
   on `SAFE_ATTRIBUTES` to be readable at all, which closes the classic escape
   `().__class__.__bases__[0].__subclasses__()` and every variation of it, and
   also stops a strategy reaching `view.history` internals it has no business
   touching.
3. **A replaced `__builtins__`.** `open`, `getattr`, `eval`, `exec`, `type`,
   `__import__` and `globals` do not exist inside the sandbox. There is no name
   in scope that returns a module, a class, or a file.

**What is deliberately not solved here.** This stops the code reaching *data*
it should not see. It is not a defence against a hostile adversary running code
on your machine — a determined person can still write an expression that takes
a very long time, and CPython has no reliable in-process way to interrupt that.
`while` is banned and `range` is capped for exactly that reason, but the honest
protection against a runaway strategy is the wall-clock timeout the job runner
imposes from outside, not anything in this file. Recorded as S-021.

The intended threat model is **the operator pasting their own code, or an LLM's
code, and wanting the backtest to still mean something.** Against that, the
firewall holding is the whole point.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from eulerlab.backtest.strategy import MarketView, Strategy

MAX_RANGE = 100_000
"""A `range` larger than this raises. With `while` banned, a comprehension over
a huge range is the only remaining way to write an accidental infinite loop."""

ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.Module,
        ast.FunctionDef,
        ast.Return,
        ast.Assign,
        ast.AugAssign,
        ast.AnnAssign,
        ast.For,
        ast.If,
        ast.IfExp,
        ast.Expr,
        ast.Pass,
        ast.Break,
        ast.Continue,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Del,
        ast.Attribute,
        ast.Subscript,
        ast.Slice,
        ast.Index if hasattr(ast, "Index") else ast.Slice,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Constant,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Set,
        ast.ListComp,
        ast.DictComp,
        ast.SetComp,
        ast.GeneratorExp,
        ast.comprehension,
        ast.Lambda,
        ast.arguments,
        ast.arg,
        ast.keyword,
        ast.Starred,
        ast.JoinedStr,
        ast.FormattedValue,
        # operators and comparators
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Not,
        ast.And,
        ast.Or,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Is,
        ast.IsNot,
    }
)

SAFE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # MarketView — the entire surface a strategy is allowed
        "as_of",
        "history",
        "symbols",
        "latest",
        "close",
        # PanelRow
        "day",
        "symbol",
        "volume",
        "turnover",
        "isin",
        # date
        "year",
        "month",
        "weekday",
        "isoformat",
        "toordinal",
        # ordinary container methods
        "items",
        "keys",
        "values",
        "get",
        "append",
        "extend",
        "sort",
        "index",
        "count",
        "copy",
        "upper",
        "lower",
        "startswith",
        "endswith",
        "strip",
        "split",
        "join",
        "add",
        "update",
    }
)

SAFE_BUILTINS: dict[str, Any] = {
    "len": len,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "reversed": reversed,
    "enumerate": enumerate,
    "zip": zip,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
    "any": any,
    "all": all,
    "pow": pow,
    "divmod": divmod,
    "True": True,
    "False": False,
    "None": None,
}
"""Notice what is absent: `open`, `getattr`, `setattr`, `eval`, `exec`,
`compile`, `type`, `vars`, `dir`, `globals`, `locals`, `__import__`, `input`,
`help`. Every one of those returns something with reach — a file, a module, a
class, or a namespace — and reach is the thing being removed."""


class UnsafeStrategy(ValueError):
    """The submitted code does something a strategy is not allowed to do.

    Raised with the line number and a plain explanation, because the person
    reading it is usually trying to do something legitimate and needs to know
    which of the rules they hit.
    """


def _describe(node: ast.AST) -> str:
    """Turn a rejected node into an explanation rather than a class name."""
    return {
        "Import": "imports are not available; a strategy computes from the view it is given",
        "ImportFrom": "imports are not available; a strategy computes from the view it is given",
        "While": (
            "`while` is not available. Loop over symbols or a bounded range instead — "
            "an unbounded loop cannot be interrupted safely once it starts"
        ),
        "ClassDef": "classes are not available; write a function",
        "With": "`with` is not available; there is nothing to open",
        "Try": "`try` is not available; let errors surface rather than hiding them",
        "Raise": "`raise` is not available",
        "Global": "`global` is not available; a strategy must be pure",
        "Nonlocal": "`nonlocal` is not available; a strategy must be pure",
        "Delete": "`del` is not available",
        "Yield": "generators are not available; return a dict of weights",
        "YieldFrom": "generators are not available; return a dict of weights",
        "Await": "async is not available",
        "AsyncFunctionDef": "async is not available",
        "Assert": "`assert` is not available",
        "Lambda": "",
    }.get(type(node).__name__, f"`{type(node).__name__}` is not permitted here")


def check(source: str) -> ast.Module:
    """Parse and validate. Raises `UnsafeStrategy` with a reason, or returns the tree."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        msg = f"line {exc.lineno}: {exc.msg}"
        raise UnsafeStrategy(msg) from exc

    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            line = getattr(node, "lineno", 0)
            where = f"line {line}: " if line else ""
            raise UnsafeStrategy(f"{where}{_describe(node)}")

        if isinstance(node, ast.Attribute) and node.attr not in SAFE_ATTRIBUTES:
            raise UnsafeStrategy(
                f"line {node.lineno}: attribute `.{node.attr}` is not readable. "
                f"A strategy may use the market view and plain arithmetic; "
                f"reaching for anything else is how the lookahead firewall gets bypassed."
            )

        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise UnsafeStrategy(f"line {node.lineno}: names beginning with `__` are not available")

        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            raise UnsafeStrategy(f"line {node.lineno}: decorators are not available")

    _check_names(tree)
    return tree


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the code defines for itself: arguments, assignments, loop
    variables, comprehension targets, nested function names.

    Collected flat rather than per-scope. That over-approximates what is in
    scope at any given point, so it can let through a name used before it is
    assigned — which is a `NameError` at run time and the author's own bug.
    It never lets through a name the sandbox does not define, which is the
    property that matters.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
            arguments = node.args
            for group in (arguments.posonlyargs, arguments.args, arguments.kwonlyargs):
                names.update(a.arg for a in group)
            if arguments.vararg:
                names.add(arguments.vararg.arg)
            if arguments.kwarg:
                names.add(arguments.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            names.update(a.arg for a in node.args.args)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def _check_names(tree: ast.Module) -> None:
    """Reject any name the sandbox will not provide, at submit time.

    Without this the code still cannot reach anything — `open` and `eval` are
    simply absent from the replaced builtins, so calling one raises
    `NameError`. But that happens *during a backtest*, hundreds of rebalances
    in, as a traceback that says nothing about why. Catching it here turns a
    confusing run-time failure into "`open` is not available", at the moment
    the author can act on it.
    """
    available = _bound_names(tree) | set(SAFE_BUILTINS) | {"range"}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            continue
        if node.id in available:
            continue
        hint = (
            " It returns something with reach — a file, a module, a class or a "
            "namespace — which is exactly what the sandbox removes."
            if node.id
            in {
                "open",
                "eval",
                "exec",
                "compile",
                "getattr",
                "setattr",
                "type",
                "vars",
                "dir",
                "globals",
                "locals",
                "input",
                "help",
            }
            else ""
        )
        raise UnsafeStrategy(
            f"line {node.lineno}: `{node.id}` is not available inside a strategy.{hint}"
        )


def _guarded_range(*args: int) -> range:
    built = range(*args)
    if len(built) > MAX_RANGE:
        msg = f"range of {len(built):,} is larger than the {MAX_RANGE:,} cap"
        raise UnsafeStrategy(msg)
    return built


ENTRY_POINT = "weights"
"""The function the sandbox calls. Named rather than inferred, so a file with
several functions has one unambiguous entry."""


class SandboxedStrategy(Strategy):
    """A `Strategy` whose body is code someone typed.

    Deliberately a normal `Strategy` subclass. It goes through
    `event_driven.run` and `vector.run` exactly like `RankAndHold` does, gets
    the same `MarketView`, produces the same orders, and is subject to the same
    cost model — so a backtest of pasted code is comparable with every other
    number in the project rather than being a separate world.
    """

    sizing = "strategy"
    """Typed code returns its own weights, and they are used as typed (ADR-121)."""

    def __init__(self, source: str, *, name: str = "sandboxed", lookback: int | None = 300) -> None:
        self.name = name
        self.lookback = lookback
        self.source = source

        tree = check(source)
        namespace: dict[str, Any] = {
            "__builtins__": {**SAFE_BUILTINS, "range": _guarded_range},
        }
        compiled = compile(tree, filename="<strategy>", mode="exec")
        exec(compiled, namespace)

        entry = namespace.get(ENTRY_POINT)
        if not callable(entry):
            msg = (
                f"no `{ENTRY_POINT}(view)` function found. A strategy is one function "
                f"taking the market view and returning {{symbol: weight}}."
            )
            raise UnsafeStrategy(msg)
        self._entry = entry

    def target_weights(self, view: MarketView) -> dict[str, float]:
        result = self._entry(view)
        return _sanitise(result)

    def describe(self) -> str:
        return self.name


def _sanitise(result: Any) -> dict[str, float]:
    """Force the return value into the contract before the engine sees it.

    Checked rather than trusted. A strategy returning a list, a `None`, or a
    dict of strings would otherwise fail deep inside the engine with an error
    that says nothing about the actual mistake, which the author is the only
    person who can fix.
    """
    if result is None:
        return {}
    if not isinstance(result, Mapping):
        msg = (
            f"`{ENTRY_POINT}` returned {type(result).__name__}, not a dict. "
            f"Return {{symbol: weight}}, or an empty dict to hold nothing."
        )
        raise UnsafeStrategy(msg)

    clean: dict[str, float] = {}
    for key, value in result.items():
        if not isinstance(key, str):
            msg = f"weight key {key!r} is not a symbol string"
            raise UnsafeStrategy(msg)
        try:
            weight = float(value)
        except (TypeError, ValueError):
            msg = f"weight for {key} is {value!r}, which is not a number"
            raise UnsafeStrategy(msg) from None
        clean[key] = weight
    return clean


EXAMPLE = """\
# A strategy is one function. `view` is everything you are allowed to see:
# history up to the decision date, and nothing after it.
#
#   view.symbols()          -> sorted list of symbols
#   view.history[symbol]    -> rows, oldest first, ending on or before view.as_of
#   view.close(symbol)      -> most recent close, or None
#   row.day / .close / .volume / .turnover
#
# Return {symbol: weight}. Weights are normalised by the engine, so they need
# not sum to 1. An omitted symbol means zero.

def weights(view):
    scores = {}
    for symbol in view.symbols():
        rows = view.history[symbol]
        if len(rows) < 253:
            continue
        # 12-month return, skipping the most recent month
        past = rows[-253].close
        recent = rows[-21].close
        if past > 0:
            scores[symbol] = recent / past - 1.0

    ranked = sorted(scores, key=lambda s: -scores[s])[:30]
    if not ranked:
        return {}
    return {symbol: 1.0 / len(ranked) for symbol in ranked}
"""
