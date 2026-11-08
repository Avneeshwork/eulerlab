"""The forward-test stage: a gate-promoted strategy trading on paper, measured against its backtest (T-3311).

    gate PROMOTE (ledger, kind "gate")  ->  promoted, waiting for the operator
    + a paper deployment the operator started on or after that day  ->  forward_testing
    + an active live deployment  ->  live (still blocked: T-3336)

**The stage is derived, never stored** (`strategies/__init__.py`): it is read
from the trial ledger and the deployment folders each time, so the page cannot
show a stage the system did not reach.

**What can be deployed.** A registered strategy whose ledger subjects include
a promoted hypothesis, or the promoted hypothesis itself (`H-NNNN`). A
hypothesis trades exactly its card's one configuration, built by
`codegen.build_one`, the builder the lab and validation use, so the paper book
is the strategy the gate judged. The operator chose on 2026-11-02 to start each
forward test by hand from the Deploy page (ADR-117).

**Leaving the stage.** `ready_for_live` reads `forward_test:` in
`mandate.yaml`. The mandate is operator-owned and that section does not exist
until the operator writes it; until then the answer is "not set", never a
default chosen here.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.validation.ledger import LEDGER_PATH, sharpe_of
from eulerlab.validation.ledger import read as read_ledger

HYPOTHESES = Path("hypotheses")
_HYPOTHESIS = re.compile(r"H-\d{4}")
TRADING_DAYS = 252


def is_hypothesis(strategy_id: str) -> bool:
    return bool(_HYPOTHESIS.fullmatch(strategy_id))


# --- promotion ---------------------------------------------------------------


def verdicts(path: Path = LEDGER_PATH) -> dict[str, tuple[str, date]]:
    """Each subject's latest gate verdict and its day. A later KILL replaces an earlier PROMOTE."""
    out: dict[str, tuple[str, date]] = {}
    for entry in read_ledger(path):
        if entry.kind != "gate":
            continue
        verdict = str(entry.outcome.get("verdict", ""))
        try:
            day = date.fromisoformat(entry.logged_at[:10])
        except ValueError:
            continue
        out[entry.subject] = (verdict, day)
    return out


def promoted_on(strategy_id: str, gate: dict[str, tuple[str, date]]) -> date | None:
    """The day the gate promoted this strategy, or None. Matches the id and its ledger subjects."""
    subjects = [strategy_id]
    if not is_hypothesis(strategy_id):
        from eulerlab.strategies import REGISTRY

        declaration = REGISTRY.get(strategy_id)
        subjects += list(declaration.ledger_subjects) if declaration else []
    days = [gate[s][1] for s in subjects if s in gate and gate[s][0].upper().startswith("PROMOTE")]
    return min(days) if days else None


def paper_on(strategy_id: str, gate: dict[str, tuple[str, date]]) -> date | None:
    """The day the gate allowed paper trading: a PROMOTE or a PAPER verdict (ADR-141)."""
    subjects = [strategy_id]
    if not is_hypothesis(strategy_id):
        from eulerlab.strategies import REGISTRY

        declaration = REGISTRY.get(strategy_id)
        subjects += list(declaration.ledger_subjects) if declaration else []
    days = [
        gate[s][1]
        for s in subjects
        if s in gate and gate[s][0].upper().startswith(("PROMOTE", "PAPER"))
    ]
    return min(days) if days else None


# --- a promoted hypothesis as a strategy ----------------------------------------


class GatedCard(RankAndHold):
    """A hypothesis card's one configuration, with the rebalance the card fixed."""

    def __init__(self, base: RankAndHold, rebalance_every: int, hypothesis: str) -> None:
        super().__init__(
            base.feature, top_n=base.top_n, min_names=base.min_names, min_turnover=base.min_turnover
        )
        self.rebalance_every = rebalance_every
        self.name = f"{hypothesis}: {self.name}"


def card_path(hypothesis: str, root: Path = HYPOTHESES) -> Path:
    return root / f"{hypothesis}.yaml"


def build(hypothesis: str, root: Path = HYPOTHESES) -> GatedCard:
    """The strategy a hypothesis card declares. Raises ValueError if it cannot be traded as one book."""
    from eulerlab.filecache import read_yaml
    from eulerlab.research import codegen

    path = card_path(hypothesis, root)
    if not path.exists():
        msg = f"no card at {path}"
        raise ValueError(msg)
    # A copy: the parsed card is shared through the cache and codegen is given
    # the configuration to build from.
    spec = copy.deepcopy(read_yaml(path)) or {}
    configs = spec.get("configurations") or []
    if len(configs) != 1:
        msg = (
            f"{hypothesis} declares {len(configs)} configurations; a paper book trades one, "
            "and choosing among them after the gate would be a selection the gate never priced"
        )
        raise ValueError(msg)
    try:
        built = codegen.build_one(configs[0])
    except Exception as exc:
        raise ValueError(f"{hypothesis} cannot be built: {exc}") from exc
    if not isinstance(built.strategy, RankAndHold):
        msg = f"{hypothesis} is not a rank-and-hold card; only those deploy today"
        raise ValueError(msg)
    return GatedCard(built.strategy, built.rebalance, hypothesis)


def blocker(
    hypothesis: str,
    *,
    ledger: Path = LEDGER_PATH,
    root: Path = HYPOTHESES,
) -> str:
    """Why a hypothesis cannot be paper-traded, or "" when it can."""
    gate = verdicts(ledger)
    if hypothesis not in gate:
        return f"{hypothesis} has never been through the gate (make gate H={hypothesis})"
    verdict, _ = gate[hypothesis]
    if not verdict.upper().startswith(("PROMOTE", "PAPER")):
        return f"the gate's verdict on {hypothesis} is {verdict}; a strategy the gate kills is dead"
    try:
        build(hypothesis, root)
    except ValueError as exc:
        return str(exc)
    return ""


# --- the stage -------------------------------------------------------------------


def stage(
    strategy_id: str,
    *,
    gate: dict[str, tuple[str, date]] | None = None,
    deployments: Iterable[Any] | None = None,
) -> str:
    """`live`, `forward_testing`, `promoted`, `paper_evaluation`, `paper_candidate`, or "".

    A PAPER verdict (ADR-141) reaches only the `paper_` stages, which the live
    preflight does not accept: paper trading, never live money.
    """
    from eulerlab.deploy import deployments as store

    gate = verdicts() if gate is None else gate
    mine = [
        d
        for d in (store.all_deployments() if deployments is None else deployments)
        if d.strategy_id == strategy_id and d.status == "active"
    ]
    if any(d.mode == "live" for d in mine):
        return "live"
    since = promoted_on(strategy_id, gate)
    if since is None:
        paper = paper_on(strategy_id, gate)
        if paper is None:
            return ""
        if any(d.mode == "paper" and d.start >= paper for d in mine):
            return "paper_evaluation"
        return "paper_candidate"
    if any(d.mode == "paper" and d.start >= since for d in mine):
        return "forward_testing"
    return "promoted"


# --- the report ------------------------------------------------------------------


@dataclass
class Report:
    deployment: str
    strategy: str
    start: str
    days: int = 0
    total_return: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    backtest_sharpe: float | None = None
    ready: bool | None = None
    """None while the mandate sets no forward-test rule."""
    reasons: list[str] = field(default_factory=list)


def _returns(values: Sequence[float]) -> list[float]:
    return [b / a - 1.0 for a, b in pairwise(values) if a]


def _sharpe(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return None if var <= 0 else mean / math.sqrt(var) * math.sqrt(TRADING_DAYS)


def _max_drawdown(values: Sequence[float]) -> float | None:
    if not values:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1.0)
    return worst


def backtest_sharpe(strategy_id: str, path: Path = LEDGER_PATH) -> float | None:
    """The best Sharpe the ledger holds for this strategy or its subjects."""
    subjects = {strategy_id}
    if not is_hypothesis(strategy_id):
        from eulerlab.strategies import REGISTRY

        declaration = REGISTRY.get(strategy_id)
        subjects |= set(declaration.ledger_subjects) if declaration else set()
    found = [
        s for e in read_ledger(path) if e.subject in subjects and (s := sharpe_of(e)) is not None
    ]
    return max(found) if found else None


def rules(mandate: dict[str, Any] | None = None) -> dict[str, Any]:
    """`forward_test:` from the mandate; {} until the operator writes it."""
    if mandate is None:
        from eulerlab import gates

        mandate = gates.load_mandate()
    section = mandate.get("forward_test")
    return section if isinstance(section, dict) else {}


def ready_for_live(report: Report, rule: dict[str, Any]) -> tuple[bool | None, list[str]]:
    """Whether the forward record meets the mandate's rule. None when there is no rule."""
    if not rule:
        return None, ["forward-test criteria not set in mandate.yaml (forward_test:)"]
    reasons: list[str] = []
    min_days = rule.get("min_days")
    if isinstance(min_days, int) and report.days < min_days:
        reasons.append(f"{report.days} trading days of {min_days} required")
    ratio = rule.get("min_sharpe_ratio_of_backtest")
    if isinstance(ratio, int | float):
        if report.sharpe is None or report.backtest_sharpe is None:
            reasons.append("forward or backtest Sharpe not measured yet")
        elif report.sharpe < ratio * report.backtest_sharpe:
            reasons.append(
                f"forward Sharpe {report.sharpe:.2f} is below {ratio:g} x backtest "
                f"{report.backtest_sharpe:.2f}"
            )
    floor = rule.get("max_drawdown")
    if (
        isinstance(floor, int | float)
        and report.max_drawdown is not None
        and report.max_drawdown < -abs(floor)
    ):
        reasons.append(f"drawdown {report.max_drawdown:.1%} is deeper than -{abs(floor):.0%}")
    return not reasons, reasons


def report(
    deployment: Any,
    state: dict[str, Any] | None,
    *,
    tested_sharpe: float | None,
    rule: dict[str, Any],
) -> Report:
    """One deployment's forward record from its own equity curve (`state.json`)."""
    curve = (state or {}).get("curve") or []
    values = [float(v) for _, v in curve]
    returns = _returns(values)
    out = Report(
        deployment=deployment.id,
        strategy=deployment.strategy_id,
        start=deployment.start.isoformat(),
        days=len(returns),
        total_return=(values[-1] / values[0] - 1.0) if len(values) > 1 and values[0] else None,
        sharpe=_sharpe(returns),
        max_drawdown=_max_drawdown(values),
        backtest_sharpe=tested_sharpe,
    )
    out.ready, out.reasons = ready_for_live(out, rule)
    return out


def reports(*, ledger: Path = LEDGER_PATH) -> list[Report]:
    """Every forward-testing deployment's report, newest first."""
    from eulerlab.deploy import deployments as store

    gate = verdicts(ledger)
    every = store.all_deployments()
    rule = rules()
    out: list[Report] = []
    for d in every:
        if d.mode != "paper" or d.status != "active":
            continue
        since = paper_on(d.strategy_id, gate)
        if since is None or d.start < since:
            continue
        out.append(
            report(
                d,
                store.read_state(d),
                tested_sharpe=backtest_sharpe(d.strategy_id, ledger),
                rule=rule,
            )
        )
    return out
