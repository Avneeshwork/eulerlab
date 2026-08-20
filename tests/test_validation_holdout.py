"""The holdout: reserved, and structurally unreachable.

CLAUDE.md: *read exactly once, by the operator's action. Never read it to
"check something".* A rule like that lasts exactly as long as it is
inconvenient and unenforced, so the enforcement is code and the boundary is
data.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from eulerlab.features.panel import PanelRow
from eulerlab.validation import holdout as holdout_mod


def _rows(n: int = 100, start: date = date(2024, 1, 1)) -> list[PanelRow]:
    return [
        PanelRow(
            day=start + timedelta(days=i), symbol="ACME", close=100.0, volume=1.0, turnover=1.0
        )
        for i in range(n)
    ]


def test_everything_on_or_after_the_boundary_is_removed() -> None:
    boundary = date(2024, 3, 1)
    kept, dropped = holdout_mod.truncate(_rows(), holdout_mod.Holdout(boundary, "unread"))
    assert dropped > 0
    assert all(r.day < boundary for r in kept)


def test_the_boundary_day_itself_is_withheld() -> None:
    """Inclusive would leak exactly one day, every time, silently."""
    boundary = date(2024, 2, 1)
    kept, _ = holdout_mod.truncate(_rows(), holdout_mod.Holdout(boundary, "unread"))
    assert boundary not in {r.day for r in kept}


def test_a_far_future_boundary_withholds_nothing() -> None:
    kept, dropped = holdout_mod.truncate(_rows(), holdout_mod.Holdout(date(2099, 1, 1), "unread"))
    assert dropped == 0
    assert len(kept) == 100


def test_the_count_withheld_is_reported_not_silent() -> None:
    """Accidentally excluding data costs power and must be visible; the
    asymmetry is deliberate, because accidentally including it destroys the
    only untouched evidence the project has."""
    _, dropped = holdout_mod.truncate(_rows(), holdout_mod.Holdout(date(2024, 2, 1), "unread"))
    assert dropped == 69


def test_the_real_hypothesis_declares_an_unread_holdout() -> None:
    hypothesis = holdout_mod.load(Path("hypotheses/H-0001.yaml"))
    assert hypothesis.holdout.is_unread
    assert hypothesis.holdout.starts.year >= 2024


def test_the_hypothesis_declares_red_flags_in_advance() -> None:
    """CLAUDE.md's research protocol: a hypothesis is a spec, not prose, and
    the red flags must be written before the evidence is gathered."""
    hypothesis = holdout_mod.load(Path("hypotheses/H-0001.yaml"))
    assert len(hypothesis.red_flags) >= 3
    assert hypothesis.claim
    assert len(hypothesis.configurations) >= 2


def test_configurations_are_fixed_in_advance() -> None:
    """PBO measures whether *choosing* among these is picking noise. Adding one
    after seeing results is the overfitting it exists to detect."""
    hypothesis = holdout_mod.load(Path("hypotheses/H-0001.yaml"))
    labels = {f"{c['feature']}|{c['top_n']}|{c['rebalance']}" for c in hypothesis.configurations}
    assert len(labels) == len(hypothesis.configurations)
