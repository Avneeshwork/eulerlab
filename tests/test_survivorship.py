"""Today's index list applied to old data is the bias that flatters most."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.bitemporal.store import LookaheadError
from eulerlab.bitemporal.universe import read_universe

STAMPED = "# top 250 by turnover\n# as_of: 2024-09-17\n# count: 2\nHDFCBANK\nRELIANCE\n"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "universe.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_2024_universe_is_refused_for_a_2015_backtest(tmp_path: Path) -> None:
    """The headline case. Every name in it had already survived nine years."""
    with pytest.raises(LookaheadError, match="cannot be used for 2015-01-05"):
        read_universe(_write(tmp_path, STAMPED), as_of=date(2015, 1, 5))


def test_the_same_universe_is_fine_on_a_later_date(tmp_path: Path) -> None:
    u = read_universe(_write(tmp_path, STAMPED), as_of=date(2025, 1, 5))
    assert u.symbols == ("HDFCBANK", "RELIANCE")


def test_the_boundary_date_itself_is_allowed(tmp_path: Path) -> None:
    """Known on the day it was computed, not the day after."""
    assert read_universe(_write(tmp_path, STAMPED), as_of=date(2024, 9, 17)).as_of == date(
        2024, 9, 17
    )


def test_an_undated_list_is_refused_rather_than_trusted(tmp_path: Path) -> None:
    """Unable to check is not the same as fine, and looks the same."""
    with pytest.raises(LookaheadError, match="no '# as_of:' header"):
        read_universe(_write(tmp_path, "HDFCBANK\nRELIANCE\n"), as_of=date(2015, 1, 5))


def test_comments_and_blanks_are_not_symbols(tmp_path: Path) -> None:
    path = _write(tmp_path, "# note\n# as_of: 2020-01-01\n\nTCS\n\n# trailing\nINFY\n")
    assert read_universe(path, as_of=date(2021, 1, 1)).symbols == ("TCS", "INFY")


def test_the_real_universe_file_is_dated_and_refuses_the_backtest_start() -> None:
    """Against the actual committed file, not a fixture."""
    path = Path("config/universe_top250.txt")
    if not path.exists():  # pragma: no cover - the file is committed
        pytest.skip("universe file not present")
    assert read_universe(path, as_of=date(2026, 1, 1)).as_of == date(2024, 9, 17)
    with pytest.raises(LookaheadError):
        read_universe(path, as_of=date(2015, 1, 1))
