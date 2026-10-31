"""The critic: reject a hypothesis before it costs a trial.

Every validation run spends a trial, and Sprint 15 measured what that costs —
each one raises the Deflated Sharpe bar for every candidate, including ones
already assessed. So the cheapest possible improvement to the research loop is
not a better gate. It is refusing to *spend* a trial on a hypothesis that
cannot pass.

That is this module. It runs before any backtest, reads only the card and the
existing ledger, and costs nothing.

**Everything here is knowable in advance.** No check consults price data,
because a check that looked at outcomes would itself be a form of selection —
peeking at how a hypothesis performs and then deciding whether to "officially"
test it is the oldest way to launder a trial. The critic may only use what the
card declares and what the project already knows.

**Its objections are advisory, not binding.** The critic is not a second gate.
It cannot kill anything, and the operator can register a hypothesis it
objects to. Making it binding would give an automated component veto power
over the research direction, and its checks are heuristics — good enough to
warn, nowhere near good enough to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from eulerlab.features.formula import is_known
from eulerlab.research.budget import price_search
from eulerlab.validation.ledger import read as read_ledger

# Measured in Sprint 13 on real IC series: these move together at |rho| >= 0.6
# and are closer to one finding than three.
KNOWN_CLUSTERS: tuple[frozenset[str], ...] = (
    frozenset({"low_volatility", "max_drawdown", "price_to_52w_high"}),
    frozenset({"turnover_liquidity", "illiquidity_amihud", "small_size"}),
    frozenset({"momentum_12_1", "momentum_6_1"}),
)


class Severity:
    BLOCKER = "BLOCKER"
    """Would certainly fail the gate, or cannot be evaluated at all."""
    CONCERN = "CONCERN"
    """Materially weakens the case; worth answering before spending a trial."""
    NOTE = "NOTE"


@dataclass(frozen=True)
class Objection:
    severity: str
    rule: str
    detail: str

    def line(self) -> str:
        return f"  {self.severity:<8} {self.rule:<26} {self.detail}"


@dataclass
class Review:
    hypothesis: str
    objections: list[Objection]

    @property
    def blockers(self) -> list[Objection]:
        return [o for o in self.objections if o.severity == Severity.BLOCKER]

    @property
    def worth_testing(self) -> bool:
        """Advisory. A blocker means a trial would almost certainly be wasted."""
        return not self.blockers

    def render(self) -> str:
        lines = [f"\ncritic: {self.hypothesis}", ""]
        if not self.objections:
            lines.append("  no objections. Nothing here predicts failure.")
        else:
            lines.extend(o.line() for o in self.objections)
        lines.append("")
        if self.blockers:
            lines.append(
                f"{len(self.blockers)} blocker(s). Spending a trial here would raise the\n"
                "bar for every other candidate and almost certainly fail anyway.\n"
                "The critic cannot refuse — that is the operator's call — but it advises against."
            )
        else:
            lines.append("No blockers. Testing this is a defensible use of a trial.")
        return "\n".join(lines)


def _features_in(configs: list[dict[str, Any]]) -> set[str]:
    return {str(c.get("feature", "")) for c in configs if c.get("feature")}


def review(path: Path, *, available_years: float) -> Review:
    """Everything knowable about a card before spending anything."""
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configs = list(spec.get("configurations") or [])
    features = _features_in(configs)
    out: list[Objection] = []

    # --- can it even be run? ---
    unknown = sorted(f for f in features if not is_known(f))
    if unknown:
        out.append(
            Objection(
                Severity.BLOCKER,
                "unknown feature",
                f"{', '.join(unknown)} — not in the library, so the card cannot be built",
            )
        )

    if len(configs) < 2:
        out.append(
            Objection(
                Severity.BLOCKER,
                "too few configurations",
                f"{len(configs)}; PBO cannot measure selection with fewer than 2",
            )
        )

    # --- has this been asked before? ---
    subjects = [e.subject for e in read_ledger()]
    stem = path.stem
    prior = [s for s in subjects if s == stem]
    if prior:
        out.append(
            Objection(
                Severity.CONCERN,
                "already evaluated",
                f"{stem} appears {len(prior)} time(s) in the trial ledger; re-testing "
                f"the same claim is the resubmission the ledger exists to expose",
            )
        )

    for cluster in KNOWN_CLUSTERS:
        shared = features & cluster
        if len(shared) > 1:
            out.append(
                Objection(
                    Severity.CONCERN,
                    "one finding, not several",
                    f"{', '.join(sorted(shared))} were measured in Sprint 13 as a single "
                    f"cluster (IC correlation >= 0.6). PBO will read them as separate "
                    f"choices when they are not",
                )
            )

    # --- what would it have to achieve? ---
    cost = price_search(1, available_years=available_years)
    out.append(
        Objection(
            Severity.NOTE,
            "bar after this trial",
            f"Sharpe {cost.bar_after:.2f} from noise alone at {cost.trials_after} trials",
        )
    )
    if not cost.affordable:
        out.append(
            Objection(
                Severity.BLOCKER,
                "unaffordable",
                f"needs {cost.years_needed_after:.1f}y of history, {available_years:.1f}y available",
            )
        )

    # --- does the card argue against itself? ---
    flags = [str(f) for f in spec.get("red_flags") or []]
    disqualifying = [
        f
        for f in flags
        if any(
            phrase in f.lower()
            for phrase in (
                "cannot be cited",
                "must not be cited",
                "is not evidence",
                "known to be wrong",
            )
        )
    ]
    if disqualifying:
        out.append(
            Objection(
                Severity.CONCERN,
                "own evidence disowned",
                f"{len(disqualifying)} red flag(s) say the supporting evidence cannot be "
                f"used. Testing anyway means proceeding on a case the card itself retracts",
            )
        )

    if str(spec.get("status", "draft")) != "registered":
        out.append(
            Objection(
                Severity.NOTE,
                "not registered",
                f"status is {spec.get('status', 'draft')!r}; the gate acts on registered cards",
            )
        )
    return Review(hypothesis=stem, objections=out)
