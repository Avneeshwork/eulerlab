"""``hrp``: hierarchical risk parity (Lopez de Prado 2016)."""

from __future__ import annotations

import numpy as np

from eulerlab.risk.sizing.common import Matrix


def _single_linkage_order(dist: Matrix) -> list[int]:
    """Leaf order of single-linkage clustering: the quasi-diagonal order of
    HRP's step 2. Ties merge the lowest indices first, so it is deterministic."""
    clusters: list[list[int]] = [[i] for i in range(len(dist))]
    while len(clusters) > 1:
        best: tuple[float, int, int] | None = None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                d = float(dist[np.ix_(clusters[a], clusters[b])].min())
                if best is None or d < best[0] - 1e-15:
                    best = (d, a, b)
        assert best is not None
        _, a, b = best
        merged = clusters[a] + clusters[b]
        clusters = [c for k, c in enumerate(clusters) if k not in (a, b)] + [merged]
    return clusters[0]


def _cluster_variance(cov: Matrix, members: list[int]) -> float:
    sub = cov[np.ix_(members, members)]
    ivp = 1.0 / np.diag(sub)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp(cov: Matrix) -> Matrix:
    """Lopez de Prado (2016): cluster on correlation distance, order the names
    so similar ones sit together, then split weight top-down between halves in
    inverse proportion to each half's variance."""
    sd = np.sqrt(np.diag(cov))
    corr = np.clip(cov / np.outer(sd, sd), -1.0, 1.0)
    dist = np.sqrt(0.5 * (1.0 - corr))
    np.fill_diagonal(dist, 0.0)
    # Distance between the columns of the distance matrix, as in the paper.
    dd = np.sqrt(((dist[:, None, :] - dist[None, :, :]) ** 2).sum(axis=2))
    order = _single_linkage_order(dd)
    weights = np.ones(len(order))
    stack = [order]
    while stack:
        nxt: list[list[int]] = []
        for members in stack:
            if len(members) < 2:
                continue
            left, right = members[: len(members) // 2], members[len(members) // 2 :]
            v_left, v_right = _cluster_variance(cov, left), _cluster_variance(cov, right)
            alpha = 1.0 - v_left / (v_left + v_right)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
            nxt += [left, right]
        stack = nxt
    out: Matrix = weights / weights.sum()
    return out
