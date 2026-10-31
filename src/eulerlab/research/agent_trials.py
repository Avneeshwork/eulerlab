"""The one path by which an agent may spend a trial: a weekly allowance, set by the operator (ADR-089).

Until 2026-10-29 the research loop stopped at drafts, on the argument in
`research/orchestrator.py`: an agent that originates an idea and also decides
to test it is selecting on its own output. The operator chose to let it test,
within 5 trials a week (`config/agent_trials.yaml`). This module is how that
choice is kept to its terms:

- **Every evaluation is a trial in the same append-only log** as `make ic`,
  `make optimize` and `make walk` (`features/trials.py`), labelled
  `agent|<card>|...`, so it raises the noise bar like any other and
  `budget.searches_run` counts it. It is written **before** the result is
  read, so an interrupted run still counts what it spent.
- **The allowance is checked before anything is computed.** A card is tested
  only if all its trials fit in what is left of the week (IST, Monday to
  Sunday); a card's configurations are never cut down to fit, because the card
  pre-registered all of them.
- **Never the holdout.** The panel is truncated at the card's holdout date
  before either step sees it (`validation/holdout.truncate`).
- **Only the card's own configurations.** Built by `research/codegen.py` from
  tested library primitives; no sweep, no tuning, no generated code.
- **Two steps, cheapest first.** An IC screen per distinct feature (one trial
  each); only a card whose every feature passes is backtested (one trial per
  configuration, Tier A, realistic costs).

It never runs the gate, never writes the validation ledger and never reads
`gates.py` or `mandate.yaml`. A survivor goes to the operator's inbox.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.features import trials
from eulerlab.features.panel import PanelRow, trading_days

IST = ZoneInfo("Asia/Kolkata")
CONFIG = Path("config/agent_trials.yaml")
PREFIX = "agent|"


class Allowance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    per_week: int = Field(ge=0, le=50)
    ic_horizon: int = Field(default=21, ge=1, le=252)
    ic_step: int = Field(default=5, ge=1, le=21)
    min_ic: float = Field(default=0.02, ge=0.0)
    min_t: float = Field(default=2.0, ge=0.0)


def load_allowance(path: Path = CONFIG) -> Allowance:
    return Allowance.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


class OverAllowance(RuntimeError):
    pass


def week_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(UTC)


def spent_this_week(now: datetime | None = None, path: Path | None = None) -> int:
    path = path or trials.TRIALS_PATH
    if not path.exists():
        return 0
    import json

    since = week_start(now or datetime.now(UTC))
    used = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not str(row.get("feature", "")).startswith(PREFIX):
            continue
        try:
            at = datetime.fromisoformat(str(row.get("logged_at")))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if at >= since:
            used += 1
    return used


def left_this_week(
    allowance: Allowance, now: datetime | None = None, path: Path | None = None
) -> int:
    return max(allowance.per_week - spent_this_week(now, path), 0)


@dataclass
class Screen:
    feature: str
    mean_ic: float
    t_stat: float
    periods: int
    passed: bool


@dataclass
class Backtested:
    label: str
    days: list[str]
    values: list[float]
    total_return: float
    annualised: float
    max_drawdown: float
    robust_sharpe: float
    costs: float


@dataclass
class CardTest:
    card: str
    trials_spent: int = 0
    research_window: str = ""
    screens: list[Screen] = field(default_factory=list)
    backtests: list[Backtested] = field(default_factory=list)
    stopped: str = ""

    @property
    def screened_in(self) -> bool:
        return bool(self.screens) and all(s.passed for s in self.screens)


def cost_of(card_path: Path) -> tuple[int, list[str], list[Any]]:
    """Trials a full test of this card would spend: one per feature, plus one per configuration."""
    from eulerlab.research import codegen

    built = codegen.build_from_card(card_path)
    spec = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
    features = sorted(
        {str(c.get("feature")) for c in spec.get("configurations") or [] if c.get("feature")}
    )
    return len(features) + len(built), features, built


def _log(
    card_id: str, what: str, days: Sequence[Any], n: int, ic: float, t: float, path: Path | None
) -> None:
    trials.append(
        trials.Trial(
            logged_at=trials.now_iso(),
            feature=f"{PREFIX}{card_id}|{what}",
            horizon_days=0,
            step_days=0,
            panel_start=str(days[0]) if days else "",
            panel_end=str(days[-1]) if days else "",
            n_periods=n,
            mean_ic=round(ic, 6),
            t_stat=round(t, 4),
        ),
        path or trials.TRIALS_PATH,
    )


Reader = Callable[[], list[PanelRow]]


def card_label(card_id: str, card_path: Path) -> str:
    """A registered card's id, or a staged draft's folder name (drafts share a placeholder id)."""
    digits = card_id.removeprefix("H-")
    return card_id if card_id.startswith("H-") and digits.isdigit() else card_path.parent.name


def test_card(
    card_path: Path,
    *,
    allowance: Allowance | None = None,
    read_rows: Reader | None = None,
    now: datetime | None = None,
    trials_path: Path | None = None,
) -> CardTest:
    """Screen a card, and backtest it if every feature passes. Raises `OverAllowance` before spending."""
    from eulerlab.backtest import vector
    from eulerlab.backtest.report import _annualised, _max_drawdown, _robust_sharpe
    from eulerlab.features.formula import resolve
    from eulerlab.features.ic import evaluate
    from eulerlab.validation import holdout

    allowance = allowance or load_allowance()
    card = holdout.load(card_path)
    full_cost, features, built = cost_of(card_path)
    left = left_this_week(allowance, now, trials_path)
    if full_cost > left:
        msg = (
            f"{card.id} needs {full_cost} trials ({len(features)} screens, {len(built)} backtests); "
            f"{left} of this week's {allowance.per_week} are left"
        )
        raise OverAllowance(msg)

    if read_rows is None:
        from eulerlab.features.panel import read_panel

        read_rows = read_panel
    rows, dropped = holdout.truncate(read_rows(), card.holdout)
    days = trading_days(rows)
    label = card_label(card.id, card_path)
    out = CardTest(label)
    if not days:
        out.stopped = "no panel rows before the holdout"
        return out
    out.research_window = f"{days[0]} to {days[-1]} ({dropped:,} holdout rows withheld)"

    for name in features:
        result = evaluate(rows, resolve(name), horizon=allowance.ic_horizon, step=allowance.ic_step)
        _log(label, f"ic|{name}", days, result.n, result.mean_ic, result.t_stat, trials_path)
        out.trials_spent += 1
        out.screens.append(
            Screen(
                name,
                round(result.mean_ic, 4),
                round(result.t_stat, 2),
                result.n,
                result.mean_ic >= allowance.min_ic and result.t_stat >= allowance.min_t,
            )
        )
    if not out.screened_in:
        out.stopped = "screened out: no feature showed an edge before costs"
        return out

    for b in built:
        bt = vector.run(rows, b.strategy, rebalance_every=b.rebalance, asset_class="equity")
        _log(label, f"bt|{b.label}", days, len(bt.days), 0.0, 0.0, trials_path)
        out.trials_spent += 1
        out.backtests.append(
            Backtested(
                label=b.label,
                days=[d.isoformat() for d in bt.days],
                values=[round(v, 2) for v in bt.equity],
                total_return=round(bt.total_return, 4),
                annualised=round(_annualised(bt), 4),
                max_drawdown=round(_max_drawdown(bt), 4),
                robust_sharpe=round(_robust_sharpe(bt), 3),
                costs=round(bt.total_cost, 2),
            )
        )
    return out
