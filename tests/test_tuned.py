"""Adopting a sweep winner as a strategy's real parameters.

Promoting the best of a grid is exactly the max-of-N selection `optimize.py`
was written to expose, so most of these tests guard the conditions that keep it
honest rather than the mechanics of applying a number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eulerlab.intraday import tuned
from eulerlab.strategies.intraday.papers import PaperRules


def _sweep(tmp_path: Path, *, dry_run: bool, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "sweeps.jsonl"
    path.write_text(
        json.dumps(
            {
                "at": "2026-08-25T12:00:00+00:00",
                "start": "2026-06-01",
                "end": "2026-08-23",
                "dry_run": dry_run,
                "trials_before": 12,
                "trials_after": 12 if dry_run else 192,
                "required_t": 3.24,
                "skipped": [],
                "rows": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _row(strategy_id: str, best: float, median: float, **kwargs: object) -> dict[str, object]:
    row: dict[str, object] = {
        "strategy_id": strategy_id,
        "market": "us",
        "symbol": "QQQ",
        "candidates": 9,
        "best_pnl": best,
        "median_pnl": median,
        "fills": 23,
        "win_rate": 0.5,
        "sessions": 58,
        "best_params": {"stop_atr_mult": 2.0, "target_r": 3.0},
        "settings": [],
        "error": "",
    }
    row.update(kwargs)
    return row


def test_a_dry_run_is_never_adopted_from(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The condition that makes the whole thing defensible.

    A dry run's numbers are identical to a recorded one and it spends no
    trials. Adopting from it takes the selection bias without the denominator
    that corrects for it — the worst of both worlds.
    """
    path = _sweep(tmp_path, dry_run=True, rows=[_row("orb_breakout", 25_668.0, 19_622.0)])
    from eulerlab import optimize_store

    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)
    assert tuned.load() == {}


def test_a_recorded_sweep_is_adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import optimize_store

    path = _sweep(tmp_path, dry_run=False, rows=[_row("orb_breakout", 25_668.0, 19_622.0)])
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)

    adoptions = tuned.load()
    assert adoptions["orb_breakout"].adopted
    assert adoptions["orb_breakout"].params["stop_atr_mult"] == 2.0


def test_nothing_is_adopted_from_a_losing_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where every setting lost, the best is the least-bad loss.

    Adopting it is fitting noise with extra steps, and the published parameters
    are the better default. The record is still kept: "looked and found
    nothing" is a result.
    """
    from eulerlab import optimize_store

    path = _sweep(tmp_path, dry_run=False, rows=[_row("vwap_reversion", -112_370.0, -112_616.0)])
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)

    adoption = tuned.load()["vwap_reversion"]
    assert not adoption.adopted
    assert adoption.params == {}
    assert "lost money" in adoption.reason


def test_rules_fall_back_to_the_paper_when_nothing_was_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import optimize_store

    path = _sweep(tmp_path, dry_run=False, rows=[_row("vwap_reversion", -1.0, -2.0)])
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)
    tuned.refresh()

    rules = tuned.rules_for("vwap_reversion")
    assert isinstance(rules, PaperRules)
    assert rules.stop_atr_mult == PaperRules().stop_atr_mult
    tuned.ADOPTIONS.clear()


def test_rules_apply_the_adopted_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import optimize_store

    path = _sweep(tmp_path, dry_run=False, rows=[_row("orb_breakout", 25_668.0, 19_622.0)])
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)
    tuned.refresh()

    rules = tuned.rules_for("orb_breakout")
    assert isinstance(rules, PaperRules)
    assert rules.stop_atr_mult == 2.0
    assert rules.target_r == 3.0
    tuned.ADOPTIONS.clear()


def test_only_moved_parameters_count_as_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grid often lands on the paper's own value for one of its parameters.

    Reporting that as a change overstates what the sweep found, and it is the
    kind of overstatement nobody checks.
    """
    from eulerlab import optimize_store

    defaults = PaperRules()
    row = _row(
        "orb_breakout",
        1.0,
        0.5,
        best_params={
            "stop_atr_mult": 2.0,
            "target_r": float(defaults.target_r),  # unchanged from the paper
        },
    )
    path = _sweep(tmp_path, dry_run=False, rows=[row])
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)

    changed = tuned.load()["orb_breakout"].changed
    assert "stop_atr_mult" in changed
    assert "target_r" not in changed


def test_tail_share_is_zero_for_a_losing_best(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A share of a loss is not a quantity anyone can act on."""
    from eulerlab import optimize_store

    path = _sweep(tmp_path, dry_run=False, rows=[_row("x", -100.0, -110.0)])
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)
    assert tuned.load()["x"].tail_share == 0.0


def test_a_partial_sweep_does_not_unadopt_everything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug a subset sweep introduced, and the reason `load` reads all of them.

    `make optimize ONLY=...` writes a document containing only what it swept.
    Reading the newest sweep as the whole world meant a four-strategy run
    silently un-adopted the twenty already measured — no error, no warning, the
    adoptions simply stopped existing.
    """
    from eulerlab import optimize_store

    path = tmp_path / "sweeps.jsonl"
    optimize_store.record(
        [_store_row("orb_breakout", 25_668.0, 19_622.0)],
        trials_before=0,
        trials_after=9,
        required_t=3.0,
        start="2026-06-01",
        end="2026-08-23",
        dry_run=False,
        run_id="first",
        path=path,
    )
    optimize_store.record(
        [_store_row("orb_breakout_in", -3_284.0, -4_847.0)],
        trials_before=9,
        trials_after=18,
        required_t=3.1,
        start="2026-06-01",
        end="2026-08-23",
        dry_run=False,
        run_id="second",
        path=path,
    )
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)

    adoptions = tuned.load()
    assert set(adoptions) == {"orb_breakout", "orb_breakout_in"}
    assert adoptions["orb_breakout"].adopted
    assert not adoptions["orb_breakout_in"].adopted


def test_a_later_sweep_overwrites_the_same_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Merging must not mean the first answer wins forever."""
    from eulerlab import optimize_store

    path = tmp_path / "sweeps.jsonl"
    for run_id, best in (("first", 1_000.0), ("second", 5_000.0)):
        optimize_store.record(
            [_store_row("orb_breakout", best, 500.0)],
            trials_before=0,
            trials_after=9,
            required_t=3.0,
            start="2026-06-01",
            end="2026-08-23",
            dry_run=False,
            run_id=run_id,
            path=path,
        )
    monkeypatch.setattr(optimize_store, "SWEEPS_PATH", path)
    assert tuned.load()["orb_breakout"].best_pnl == 5_000.0


def _store_row(strategy_id: str, best: float, median: float) -> Any:
    from eulerlab import optimize_store

    return optimize_store.Row(
        strategy_id=strategy_id,
        market="us",
        symbol="QQQ",
        candidates=9,
        best_pnl=best,
        median_pnl=median,
        fills=23,
        win_rate=0.5,
        sessions=58,
        best_params={"stop_atr_mult": 2.0, "target_r": 3.0},
    )
