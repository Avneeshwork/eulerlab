"""Every signal the engineering agent coded must be pure and well-behaved (ADR-127).

The agent's branch runs this file with the new signal's own test, and CI runs it
on every merge. A module that fails `coded.problems` is never even imported.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.features import coded, library
from eulerlab.features.panel import PanelRow

GOOD = """
from __future__ import annotations
from collections.abc import Sequence
from eulerlab.features.base import Feature
from eulerlab.features.panel import PanelRow

def fn(history: Sequence[PanelRow]) -> float | None:
    return history[-1].close

FEATURE = Feature("good_one", fn, "last close", 1)
"""


def test_a_pure_module_has_no_problems() -> None:
    assert coded.problems(GOOD) == []


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("import os", "imports os"),
        ("from eulerlab.data import query", "imports from eulerlab.data"),
        ("from eulerlab.features.library import BY_NAME", "imports from eulerlab.features.library"),
        ("X = open('data/x.csv')", "calls open()"),
        ("Y = eval('1')", "calls eval()"),
        ("Z = (1).__class__", "uses __class__"),
        ("def g():\n    global FEATURE", "keeps state between calls (global or nonlocal)"),
    ],
)
def test_anything_that_could_look_ahead_or_reach_out_is_refused(line: str, problem: str) -> None:
    assert problem in coded.problems(GOOD + "\n" + line + "\n")


def test_a_module_that_parses_but_does_not_compile_is_refused() -> None:
    late = '"""Doc."""\n\nX = 1\nfrom __future__ import annotations\n'
    assert coded.problems(late + "FEATURE = 1\n")[0].startswith("does not compile")
    assert "imports os" in coded.problems("import os\n" + late)


def test_a_module_that_fails_on_import_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    (tmp_path / "boom_one.py").write_text(GOOD)

    def boom(name: str) -> object:
        raise ZeroDivisionError("at import")

    monkeypatch.setattr(importlib, "import_module", boom)
    assert coded.load({}, tmp_path) == {}


def test_a_module_without_feature_is_refused() -> None:
    assert coded.problems("X = 1\n") == ["defines no FEATURE"]


def test_a_refused_module_is_skipped_and_never_imported(tmp_path: Path) -> None:
    (tmp_path / "bad_one.py").write_text("import os\nFEATURE = 1\n")
    (tmp_path / "Not_A_Name.py").write_text(GOOD)
    assert coded.modules(tmp_path) == ["bad_one"]
    assert coded.load({}, tmp_path) == {}


def test_coded_features_cannot_replace_a_seed() -> None:
    for f in library.LIBRARY:
        assert library.BY_NAME[f.name] is f


def _history(seed: str, days: int = 420) -> list[PanelRow]:
    rng = random.Random(seed)
    price, out = 100.0, []
    start = date(2020, 1, 1)
    for i in range(days):
        price *= math.exp(rng.gauss(0, 0.02))
        volume = 0.0 if i % 97 == 0 else rng.uniform(1e4, 1e6)
        out.append(PanelRow(start + timedelta(days=i), "TEST", price, volume, volume * price))
    return out


@pytest.mark.parametrize("name", coded.modules())
def test_each_coded_feature_is_loaded_pure_and_well_behaved(name: str) -> None:
    source = (coded.HERE / f"{name}.py").read_text(encoding="utf-8")
    assert coded.problems(source) == []
    feature = library.BY_NAME[name]
    history = _history(name)
    before = [(r.close, r.volume) for r in history]
    assert feature(history[: max(feature.min_history - 1, 0)]) is None
    for end in range(max(feature.min_history, 1), len(history) + 1, 37):
        value = feature(history[:end])
        assert value is None or (isinstance(value, float) and math.isfinite(value))
        assert value == feature(list(history[:end]))  # the same answer every time
    assert [(r.close, r.volume) for r in history] == before  # input not changed
