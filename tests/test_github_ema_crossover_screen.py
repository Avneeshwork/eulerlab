from __future__ import annotations

from eulerlab.intraday import github_ema_crossover_screen as screen


def test_cross_signal_ignores_unwarmed_and_flat_ema_spread() -> None:
    assert screen._cross_signal(-0.1, 0.2, screen.SLOW - 1) == 0
    assert screen._cross_signal(-0.1, 0.0, screen.SLOW) == 0
    assert screen._cross_signal(0.0, 0.1, screen.SLOW) == 1


def test_cross_signal_emits_short_when_fast_ema_falls_below_slow() -> None:
    assert screen._cross_signal(0.01, -0.01, screen.SLOW) == -1


def test_cross_signal_does_not_repeat_without_a_new_cross() -> None:
    assert screen._cross_signal(0.1, 0.2, screen.SLOW) == 0
    assert screen._cross_signal(-0.2, -0.1, screen.SLOW) == 0
