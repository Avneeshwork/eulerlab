"""How many *independent* findings a set of features actually represents.

Written because the first full sweep of the seed library produced ten
features of which **none** were indistinguishable from noise and seven had
|t| > 3. That is not a good result, it is a warning: genuine feature research
kills most candidates, so a sweep that kills none is measuring something other
than ten separate effects.

It was. Correlating the features' per-period IC series showed they collapse
into roughly three groups:

| group | members | internal correlation |
|---|---|---|
| stability | low_volatility, max_drawdown, price_to_52w_high | +0.86 to +0.95 |
| liquidity/size | turnover_liquidity, illiquidity_amihud, small_size | 0.61 to 0.94 |
| momentum | momentum_12_1, momentum_6_1 | +0.79 |

Seven "significant" results are therefore about three observations, and
plausibly one story — large, liquid, stable stocks outperformed over this
window. Counting them as seven would overstate the evidence by roughly the
square root of the redundancy, in the direction that flatters.

This module exists so that arithmetic is printed automatically rather than
depending on someone remembering to check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eulerlab.features.ic import ICResult, spearman

CLUSTER_THRESHOLD = 0.6
"""Above this, two IC series are treated as the same finding.

A judgement, not a measurement, and deliberately generous: at +0.6 two
features still share only about a third of their variance, so calling them one
finding *understates* the count of independent effects. Erring that way is
correct here, because the failure being guarded against is overstating
evidence.
"""


@dataclass(frozen=True)
class Cluster:
    members: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.members)


def ic_series(results: Sequence[ICResult]) -> dict[str, dict[date, float]]:
    return {r.feature: {p.day: p.ic for p in r.periods} for r in results}


def correlation_matrix(results: Sequence[ICResult]) -> dict[tuple[str, str], float]:
    """Rank correlation of every pair's per-period IC, on shared periods only."""
    series = ic_series(results)
    names = sorted(series)
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            shared = sorted(set(series[a]) & set(series[b]))
            if len(shared) < 5:
                continue
            value = spearman([series[a][d] for d in shared], [series[b][d] for d in shared])
            if value is not None:
                out[(a, b)] = value
    return out


def cluster(results: Sequence[ICResult], *, threshold: float = CLUSTER_THRESHOLD) -> list[Cluster]:
    """Group features whose IC series move together.

    Single-linkage: any pair above the threshold joins the same group. Chosen
    over a stricter linkage because the question is "could these be one
    effect?", and single-linkage answers that conservatively — it merges
    readily, so the reported number of independent findings stays low.
    """
    correlations = correlation_matrix(results)
    names = sorted({r.feature for r in results})
    parent = {n: n for n in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b), value in correlations.items():
        if abs(value) >= threshold:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(find(name), []).append(name)
    return [Cluster(tuple(sorted(m))) for m in sorted(groups.values(), key=lambda g: (-len(g), g))]


def render(results: Sequence[ICResult], *, threshold: float = CLUSTER_THRESHOLD) -> str:
    """The paragraph that stops a sweep being read as more evidence than it is."""
    clusters = cluster(results, threshold=threshold)
    significant = [r for r in results if abs(r.t_stat) > 3.0]
    lines: list[str] = []
    add = lines.append

    add("\n" + "=" * 66)
    add("INDEPENDENCE — how many findings is this really?")
    add("=" * 66)
    add(f"features evaluated        : {len(results)}")
    add(f"with |t| > 3              : {len(significant)}")
    add(f"independent groups        : {len(clusters)}  (IC correlation >= {threshold})")
    add("")
    for group in clusters:
        if group.size > 1:
            add(f"  one finding, {group.size} features: {', '.join(group.members)}")
        else:
            add(f"  standalone            : {group.members[0]}")

    strongest = correlation_matrix(results)
    top = sorted(strongest.items(), key=lambda kv: -abs(kv[1]))[:5]
    if top:
        add("\nmost redundant pairs:")
        for (a, b), value in top:
            add(f"  {a:<22} {b:<22} {value:+.2f}")

    add(
        f"\nReading: {len(significant)} significant features is not {len(significant)} pieces of\n"
        f"evidence. It is closer to {len(clusters)}. Counting them separately would\n"
        f"overstate the case in the direction that flatters, and the trial\n"
        f"counter exists so that cannot be quietly forgotten later."
    )
    return "\n".join(lines)
