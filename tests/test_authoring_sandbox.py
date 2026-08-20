"""The sandbox: what pasted code may and may not reach.

This is a security boundary, so the tests are adversarial rather than
illustrative. Each escape below is a real technique, and the point of listing
them individually is that a future change to the allowlists has to keep every
one of them closed.

The property being defended is not "no bad code runs". It is narrower and more
important: **code cannot reach data the lookahead firewall hides from it.** A
strategy that computes nonsense is the author's problem; a strategy that reads
tomorrow's prices invalidates every number in the project.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.authoring.sandbox import (
    EXAMPLE,
    SAFE_BUILTINS,
    SandboxedStrategy,
    UnsafeStrategy,
    check,
)
from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow


def _view(days: int = 300, symbols: int = 4) -> MarketView:
    start = date(2024, 1, 1)
    history = {
        f"SYM{s}": [
            PanelRow(
                day=start + timedelta(days=d),
                symbol=f"SYM{s}",
                close=100.0 + s + d * 0.1,
                volume=1000.0,
                turnover=1e9,
                isin=f"T{s:06d}",
            )
            for d in range(days)
        ]
        for s in range(symbols)
    }
    return MarketView(as_of=start + timedelta(days=days - 1), history=history)


# --- the happy path ---------------------------------------------------------


def test_the_shipped_example_compiles_and_produces_weights() -> None:
    """The example is what the UI shows first. If it does not run, the whole
    feature reads as broken."""
    strategy = SandboxedStrategy(EXAMPLE, name="example")
    weights = strategy.target_weights(_view())
    assert weights
    assert all(isinstance(k, str) for k in weights)
    assert all(w > 0 for w in weights.values())


def test_a_strategy_holding_nothing_is_allowed() -> None:
    strategy = SandboxedStrategy("def weights(view):\n    return {}")
    assert strategy.target_weights(_view()) == {}


def test_returning_none_means_hold_nothing() -> None:
    """A common accident. It must mean 'flat', not crash the engine."""
    strategy = SandboxedStrategy("def weights(view):\n    pass")
    assert strategy.target_weights(_view()) == {}


def test_comprehensions_and_arithmetic_work() -> None:
    source = (
        "def weights(view):\n"
        "    out = {}\n"
        "    for s in view.symbols():\n"
        "        rows = view.history[s]\n"
        "        if len(rows) < 10:\n"
        "            continue\n"
        "        out[s] = rows[-1].close / rows[-10].close - 1.0\n"
        "    best = sorted(out, key=lambda k: -out[k])[:2]\n"
        "    return {k: 0.5 for k in best}\n"
    )
    assert len(SandboxedStrategy(source).target_weights(_view())) == 2


# --- escapes, each closed individually --------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("import", "import os\ndef weights(view):\n    return {}"),
        ("from-import", "from os import path\ndef weights(view):\n    return {}"),
        ("__class__ escape", "def weights(view):\n    return ().__class__"),
        ("__subclasses__", "def weights(view):\n    return ().__class__.__bases__"),
        ("__globals__", "def weights(view):\n    return weights.__globals__"),
        ("open", "def weights(view):\n    return open('/etc/passwd')"),
        ("eval", "def weights(view):\n    return eval('1+1')"),
        ("exec", "def weights(view):\n    return exec('x=1')"),
        ("getattr", "def weights(view):\n    return getattr(view, 'history')"),
        ("__import__", "def weights(view):\n    return __import__('os')"),
        ("builtins name", "def weights(view):\n    return __builtins__"),
        ("while loop", "def weights(view):\n    while True:\n        pass"),
        ("class", "class Sneaky:\n    pass\ndef weights(view):\n    return {}"),
        ("with", "def weights(view):\n    with open('x') as f:\n        return {}"),
        (
            "try swallow",
            "def weights(view):\n    try:\n        return {}\n    except:\n        return {}",
        ),
        ("global", "def weights(view):\n    global x\n    return {}"),
        ("decorator", "@staticmethod\ndef weights(view):\n    return {}"),
        ("generator", "def weights(view):\n    yield 1"),
        ("undefined module", "def weights(view):\n    return numpy.mean([1])"),
    ],
)
def test_escape_is_refused(label: str, source: str) -> None:
    with pytest.raises(UnsafeStrategy):
        SandboxedStrategy(source)


def test_the_refusal_names_the_rule_not_the_node_type() -> None:
    """An author hitting a rule needs to know which one. `Import` is not an
    explanation."""
    with pytest.raises(UnsafeStrategy, match="imports are not available"):
        check("import os")
    with pytest.raises(UnsafeStrategy, match="`while` is not available"):
        check("def weights(view):\n    while True:\n        pass")


def test_a_dangerous_builtin_is_named_and_explained() -> None:
    with pytest.raises(UnsafeStrategy, match="reach"):
        check("def weights(view):\n    return open('x')")


def test_no_builtin_that_returns_reach_is_available() -> None:
    """Asserted over the allowlist itself, so adding one is a deliberate act
    that fails this test rather than a quiet convenience."""
    forbidden = {
        "open",
        "eval",
        "exec",
        "compile",
        "getattr",
        "setattr",
        "delattr",
        "type",
        "vars",
        "dir",
        "globals",
        "locals",
        "input",
        "help",
        "__import__",
        "breakpoint",
        "memoryview",
    }
    assert not (forbidden & set(SAFE_BUILTINS))


# --- the contract with the engine -------------------------------------------


def test_a_missing_entry_point_is_a_clear_error() -> None:
    with pytest.raises(UnsafeStrategy, match="weights"):
        SandboxedStrategy("def other(view):\n    return {}")


def test_a_non_dict_return_is_rejected_with_the_actual_mistake() -> None:
    strategy = SandboxedStrategy("def weights(view):\n    return [1, 2, 3]")
    with pytest.raises(UnsafeStrategy, match="not a dict"):
        strategy.target_weights(_view())


def test_a_non_numeric_weight_is_rejected() -> None:
    strategy = SandboxedStrategy("def weights(view):\n    return {'SYM0': 'lots'}")
    with pytest.raises(UnsafeStrategy, match="not a number"):
        strategy.target_weights(_view())


def test_a_huge_range_is_capped() -> None:
    """With `while` banned, this is the remaining way to write a runaway loop."""
    strategy = SandboxedStrategy("def weights(view):\n    return {'A': sum(range(10**9))}")
    with pytest.raises(UnsafeStrategy, match="cap"):
        strategy.target_weights(_view())


def test_a_syntax_error_reports_the_line() -> None:
    with pytest.raises(UnsafeStrategy, match="line"):
        check("def weights(view)\n    return {}")


# --- the firewall itself ----------------------------------------------------


def test_the_view_contains_no_future_rows() -> None:
    """The firewall is not enforced by the sandbox; it is a property of the
    object. This asserts the property the sandbox is protecting."""
    view = _view(days=300)
    for rows in view.history.values():
        assert all(row.day <= view.as_of for row in rows)


def test_a_strategy_cannot_reach_the_panel_file() -> None:
    """The concrete thing ADR-027 was worried about: bypassing the view by
    reading the data directly."""
    for attempt in (
        "def weights(view):\n    return open('data/derived/price_panel.jsonl')",
        "def weights(view):\n    return __import__('pathlib')",
    ):
        with pytest.raises(UnsafeStrategy):
            SandboxedStrategy(attempt)


def test_it_is_a_real_strategy_the_engine_accepts() -> None:
    """No adapter, no isinstance check — the same interface as RankAndHold."""
    from eulerlab.backtest.strategy import Strategy

    assert isinstance(SandboxedStrategy(EXAMPLE), Strategy)


def test_the_same_source_gives_the_same_weights() -> None:
    """Determinism is a project-wide rule and pasted code is not exempt."""
    view = _view()
    a = SandboxedStrategy(EXAMPLE).target_weights(view)
    b = SandboxedStrategy(EXAMPLE).target_weights(view)
    assert a == b
