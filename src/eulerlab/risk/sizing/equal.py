"""``equal``: the strategy's gross exposure split equally over its names (the default)."""

from __future__ import annotations


def _equal(picks: dict[str, float], gross: float) -> dict[str, float]:
    values = list(picks.values())
    if max(values) - min(values) <= 1e-12 * max(values):
        # Already equal: returned untouched, so a strategy that sizes equally
        # itself gives byte-identical targets and stored results do not move.
        return picks
    share = gross / len(picks)
    return dict.fromkeys(picks, share)
