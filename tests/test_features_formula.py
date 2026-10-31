"""The formula language: it parses what it should, refuses what it should, never looks
forward, and reproduces the ten library features exactly (ADR-097)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from eulerlab.features import formula
from eulerlab.features.formula import FormulaError, parse, text_of
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow


def _panel(n: int = 400, *, seed: int = 7) -> list[PanelRow]:
    """A random walk with varying volume and turnover. Seeded: same rows every run."""
    rng = random.Random(seed)
    start = date(2016, 1, 1)
    close = 100.0
    rows: list[PanelRow] = []
    for i in range(n):
        close *= 1.0 + rng.gauss(0.0004, 0.02)
        volume = 1000.0 * (1.0 + rng.random() * 4)
        rows.append(
            PanelRow(
                day=start + timedelta(days=i),
                symbol="ACME",
                close=close,
                volume=volume,
                turnover=volume * close,
            )
        )
    return rows


# --- the zoo reproduces the library ---


@pytest.mark.parametrize("entry", formula.ZOO, ids=lambda e: e.name)
def test_each_zoo_formula_matches_its_library_feature_exactly(entry: formula.ZooEntry) -> None:
    rows = _panel()
    feature = formula.compile_formula(entry.text, name=entry.name, min_history=entry.min_history)
    library = BY_NAME[entry.name]
    for end in range(library.min_history, len(rows) + 1, 7):
        history = rows[:end]
        assert feature(history) == library(history), f"{entry.name} differs at row {end}"


def test_the_zoo_covers_every_library_feature() -> None:
    assert {e.name for e in formula.ZOO} == set(BY_NAME)


@pytest.mark.parametrize("entry", formula.ZOO, ids=lambda e: e.name)
def test_a_zoo_formula_refuses_the_same_short_history(entry: formula.ZooEntry) -> None:
    rows = _panel()
    if entry.min_history == 1:
        pytest.skip("needs one row; nothing shorter to refuse")
    feature = formula.compile_formula(entry.text, name=entry.name, min_history=entry.min_history)
    assert feature(rows[: entry.min_history - 1]) is None


# --- lookahead ---

OPERATOR_SAMPLE = [
    "ts_rank(delta(close, 5), 20)",
    "div(ts_mean(volume, 5), ts_std(volume, 30))",
    "sub(ts_max(ret(1), 10), ts_min(ret(1), 10))",
    "mul(sign(ret(5)), ts_sum(abs(ret(1)), 15))",
    "add(ts_mad(log(turnover), 21), delay(ts_drawdown(close, 40), 3))",
    *[e.text for e in formula.ZOO],
]


@pytest.mark.parametrize("text", OPERATOR_SAMPLE)
def test_no_value_depends_on_a_later_row(text: str) -> None:
    """The whole-history series at row t must equal the value computed from rows up to t only."""
    rows = _panel(330)
    node = parse(text)
    whole = formula.series(node, rows, len(rows))
    for t in range(0, len(rows), 11):
        assert whole[t] == formula.series(node, rows[: t + 1], 1)[0], f"{text} at row {t}"


@pytest.mark.parametrize("text", OPERATOR_SAMPLE)
def test_changing_the_future_changes_nothing_today(text: str) -> None:
    rows = _panel(330)
    cut = 290
    shuffled = rows[:cut] + [
        PanelRow(day=r.day, symbol=r.symbol, close=r.close * 3.0, volume=1.0, turnover=1.0)
        for r in rows[cut:]
    ]
    node = parse(text)
    before = formula.series(node, rows, len(rows))[:cut]
    after = formula.series(node, shuffled, len(shuffled))[:cut]
    assert before == after


# --- parsing and refusals ---


@pytest.mark.parametrize("text", OPERATOR_SAMPLE)
def test_canonical_text_round_trips(text: str) -> None:
    node = parse(text)
    assert parse(text_of(node)) == node


def test_whitespace_and_prefix_do_not_change_the_formula() -> None:
    assert parse("formula:  neg( ret(21) )") == parse("neg(ret(21))")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "open",  # not an input
        "exec(close)",
        "__import__(os)",
        "ret(close)",  # window must be a number
        "ts_mean(close, 2.5)",  # window must be whole
        "ts_mean(close, 0)",
        "ts_mean(close, 505)",
        "add(close)",
        "neg(close, close)",
        "neg(close",
        "neg(close))",
        "close; volume",
    ],
)
def test_bad_formulas_are_refused(text: str) -> None:
    with pytest.raises(FormulaError):
        parse(text)


def test_an_over_deep_formula_is_refused() -> None:
    text = "close"
    for _ in range(formula.MAX_DEPTH):
        text = f"neg({text})"
    with pytest.raises(FormulaError, match="depth"):
        parse(text)


def test_an_over_large_formula_is_refused() -> None:
    text = (
        "add(add(add(close, close), add(close, close)), add(add(close, close), add(close, close)))"
    )
    big = f"add(add({text}, {text}), {text})"
    with pytest.raises(FormulaError):
        parse(big)


def test_a_bad_formula_on_a_card_reads_as_an_unknown_feature() -> None:
    with pytest.raises(KeyError):
        formula.resolve("formula:exec(close)")
    assert not formula.is_known("formula:open")
    assert formula.is_known("formula:neg(ret(21))")
    assert formula.resolve("momentum_12_1") is BY_NAME["momentum_12_1"]


# --- behaviour ---


def test_lookback_is_the_rows_the_formula_needs() -> None:
    assert formula.lookback(parse("close")) == 1
    assert formula.lookback(parse("ret(21)")) == 22
    assert formula.lookback(parse("delay(ret(231), 21)")) == 253
    assert formula.lookback(parse("ts_mad(ret(1), 62)")) == 63


def test_division_by_zero_and_log_of_nothing_are_missing_not_errors() -> None:
    rows = _panel(10)
    assert formula.value(parse("div(close, sub(close, close))"), rows) is None
    assert formula.value(parse("log(neg(close))"), rows) is None


def test_the_same_input_gives_the_same_output() -> None:
    a = [formula.value(parse(t), _panel()) for t in OPERATOR_SAMPLE]
    b = [formula.value(parse(t), _panel()) for t in OPERATOR_SAMPLE]
    assert repr(a) == repr(b)


# --- originality ---


def test_a_zoo_formula_is_fully_similar_to_itself() -> None:
    node = parse("neg(ts_mad(ret(1), 62))")
    assert formula.max_similarity(node, formula.zoo_nodes()) == 1.0


def test_wrapping_a_zoo_formula_still_scores_as_mostly_copied() -> None:
    node = parse("neg(neg(ts_mad(ret(1), 62)))")
    assert formula.max_similarity(node, formula.zoo_nodes()) == 0.75


def test_an_unrelated_formula_shares_only_its_inputs() -> None:
    node = parse("ts_rank(ts_std(volume, 10), 40)")
    assert formula.max_similarity(node, formula.zoo_nodes()) == pytest.approx(1 / 3)


# --- a card can name a formula ---


def test_codegen_builds_a_card_that_names_a_formula() -> None:
    from eulerlab.research import codegen

    built = codegen._one({"feature": "formula:neg(ret(21))", "top_n": 20})
    assert built.label == "formula:neg(ret(21))|top20|rb21"


def test_codegen_still_refuses_python_dressed_as_a_formula() -> None:
    from eulerlab.research import codegen

    with pytest.raises(codegen.UnknownPrimitive):
        codegen._one({"feature": "formula:__import__(os)"})
