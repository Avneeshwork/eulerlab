"""The constitution: what the agents may do on their own (ADR-171).

`config/constitution.yaml` is operator-owned, like `mandate.yaml`. It holds
the four things the operator decided on 2026-11-13 and the level of every
action an agent can take:

- the test capital every paper book and forward test is sized to;
- the periods: ideas are found up to `discovery_end`, checked up to
  `backtest_end`, and everything from `forward_start` is the forward test,
  which nothing that finds or tunes an idea may read;
- the monthly budget for paid models, with the prices it is counted at;
- per action, `act`, `propose` or `never`.

The limits were spread over agent YAMLs, the mandate and code constants.
Now a caller asks here: `require("start_paper_book")` returns or raises
`NotAllowed`, and `load()` gives the numbers.

Two things the file itself cannot grant, checked when it is read:
`live_account` and `edit_gate_or_mandate` are `never`, and leverage is at
most 1. A constitution that says otherwise does not load, so every agent
action stops instead of running under a rule the operator did not write.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eulerlab.filecache import read_yaml

PATH = Path("config/constitution.yaml")
REPO_PATH = Path(__file__).resolve().parents[2] / PATH
"""The repository's own copy, whatever the working directory (ADR-184)."""

RESEARCH_START = date(2016, 1, 1)
"""The research window's first day when the constitution names none."""
SEALED_FROM = date(2026, 1, 1)
"""The 2026 forward test. No research window may reach it, whatever the file says."""
RESEARCH_END_ENV = "EULERLAB_RESEARCH_END"
"""An earlier end, to reproduce a result made on a shorter window. Never a later one."""

Level = Literal["act", "propose", "never"]

ACTIONS = (
    "register_hypothesis",
    "spend_ai_budget",
    "use_ledger_entry",
    "start_paper_book",
    "stop_paper_book",
    "demote_strategy",
    "score_forward_test",
    "change_cost_or_risk_settings",
    "merge_code",
    "edit_gate_or_mandate",
    "live_account",
)
"""Every action an agent can ask for. The file must give each one a level."""

ALWAYS_NEVER = ("live_account", "edit_gate_or_mandate")


class NotAllowed(PermissionError):
    """The constitution does not let an agent take this action by itself."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Capital(_Model):
    test_capital_inr: float = Field(gt=0)
    leverage: float = Field(default=1.0, gt=0, le=1.0)


class Periods(_Model):
    discovery_end: date
    backtest_end: date
    forward_start: date
    research_start: date = RESEARCH_START
    """The research window's first day (ADR-189). Absent from the file, 2016-01-01."""

    @model_validator(mode="after")
    def _in_order(self) -> Periods:
        if not self.research_start < self.discovery_end < self.backtest_end < self.forward_start:
            msg = "periods must run research_start < discovery_end < backtest_end < forward_start"
            raise ValueError(msg)
        return self

    def part(self, day: date) -> Literal["discovery", "selection", "forward"]:
        """Which period a session belongs to. A day after `backtest_end` is forward."""
        if day <= self.discovery_end:
            return "discovery"
        return "selection" if day <= self.backtest_end else "forward"


class Price(_Model):
    """US dollars per million tokens."""

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class Budget(_Model):
    monthly_ai_inr: float = Field(ge=0)
    usd_inr: float = Field(gt=0)
    prices_usd_per_mtok: dict[str, Price]
    unknown_paid_model: Price


class Caps(_Model):
    gate_entries_per_week: int = Field(ge=0)


class Decay(_Model):
    false_alarm: float = Field(gt=0, lt=0.5)
    horizon_sessions: int = Field(ge=20)
    watch_at: float = Field(gt=0, lt=1)


class Routing(_Model):
    """Provider names from `config/llm.yaml`, by how demanding the work is."""

    frontier: str
    mid: str
    small: str
    scoring: Literal["none"]


class Constitution(_Model):
    version: int
    owner: str
    decided: date
    capital: Capital
    periods: Periods
    budget: Budget
    caps: Caps
    decay: Decay
    routing: Routing
    actions: dict[str, Level]

    @model_validator(mode="after")
    def _every_action_has_a_level(self) -> Constitution:
        missing = [a for a in ACTIONS if a not in self.actions]
        unknown = [a for a in self.actions if a not in ACTIONS]
        if missing or unknown:
            msg = f"actions: missing {missing}, unknown {unknown}"
            raise ValueError(msg)
        granted = [a for a in ALWAYS_NEVER if self.actions[a] != "never"]
        if granted:
            msg = f"{', '.join(granted)} can only be `never`: no file gives an agent that"
            raise ValueError(msg)
        return self


def load(path: Path = PATH) -> Constitution:
    """The constitution as written. Raises if the file is missing or breaks a rule."""
    raw = read_yaml(path) if path.exists() else None
    if not isinstance(raw, dict):
        msg = f"{path} is missing or empty: no agent action is allowed without it"
        raise NotAllowed(msg)
    return Constitution.model_validate(raw)


def level(action: str, path: Path = PATH) -> Level:
    if action not in ACTIONS:
        msg = f"{action!r} is not an action the constitution knows: {', '.join(ACTIONS)}"
        raise NotAllowed(msg)
    return load(path).actions[action]


def require(action: str, *, who: str = "an agent", path: Path = PATH) -> None:
    """Return when `who` may take `action` by itself; raise `NotAllowed` otherwise."""
    found = level(action, path)
    if found != "act":
        msg = (
            f"{who} may not {action.replace('_', ' ')}: the constitution says `{found}` "
            f"({path}). Only the operator changes that."
        )
        raise NotAllowed(msg)


def refuse_agents(action: str, what: str) -> None:
    """Raise when called from inside an agent's run. For the doors no agent may open.

    `require` asks the file; this does not, because `ALWAYS_NEVER` actions have
    no setting to ask. It is called at the door itself (arming a live session,
    logging in to the live broker, sending a live order), so it holds whatever
    path led there.
    """
    from eulerlab.llm import usage

    agent, run = usage.agent_run()
    if run:
        msg = (
            f"{agent} (run {run}) may not {what}: {action.replace('_', ' ')} is never an "
            "agent's to do. Real money is the operator's own action, each time."
        )
        raise NotAllowed(msg)


def research_window(path: Path = REPO_PATH) -> tuple[date, date]:
    """(first, last) day the research screens and the rule engine may read (ADR-184).

    The end is the constitution's `backtest_end`. `EULERLAB_RESEARCH_END` may
    move it earlier, for reproducing an old result, never later. A window
    reaching the forward period or 2026 is refused, so the forward test stays
    sealed even if the file is edited carelessly.
    """
    periods = load(path).periods
    end = periods.backtest_end
    override = os.environ.get(RESEARCH_END_ENV, "").strip()
    if override:
        asked = date.fromisoformat(override)
        if asked > end:
            msg = f"{RESEARCH_END_ENV}={asked} is after the constitution's backtest_end {end}"
            raise NotAllowed(msg)
        end = asked
    return periods.research_start, sealed(end, path)


def sealed(end: date, path: Path = REPO_PATH) -> date:
    """`end`, if it stays before the forward test; otherwise refuse."""
    periods = load(path).periods
    if end >= SEALED_FROM or end >= periods.forward_start or end > periods.backtest_end:
        msg = (
            f"a research window ending {end} reaches the forward test "
            f"(backtest_end {periods.backtest_end}, sealed from {SEALED_FROM})"
        )
        raise NotAllowed(msg)
    if end < periods.research_start:
        msg = f"a research window ending {end} ends before it starts ({periods.research_start})"
        raise NotAllowed(msg)
    return end
