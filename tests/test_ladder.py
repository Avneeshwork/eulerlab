"""The incubation ladder (ADR-179): moves on evidence, demotes on trouble, never reaches real money."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab import constitution
from eulerlab.deploy import ladder, live_money
from eulerlab.llm import usage

NOW = datetime(2026, 11, 13, 11, tzinfo=UTC)
RULES = Path(__file__).parents[1] / "config" / "constitution.yaml"


def _f(stage: ladder.Stage, **more: Any) -> ladder.Facts:
    return ladder.Facts(**{"strategy": "H-0300", "stage": stage, "verdict": "PROMOTE", **more})


def test_a_gated_strategy_gets_a_paper_book() -> None:
    move = ladder.decide(_f("registered"))
    assert move is not None and (move.to, move.action) == ("paper", "start_paper")
    assert ladder.decide(_f("registered", verdict="KILL")) is None
    held = ladder.decide(_f("registered", paper_book="d1"))
    assert held is not None and held.action == ""


def test_paper_moves_to_live_prices_after_enough_clean_sessions() -> None:
    assert ladder.decide(_f("paper", paper_book="d1", paper_sessions=4)) is None
    move = ladder.decide(_f("paper", paper_book="d1", paper_sessions=5, decay="healthy"))
    assert move is not None and move.to == "live_price_paper" and move.action == ""


@pytest.mark.parametrize(
    "trouble",
    [
        {"decay": "decayed"},
        {"loss_limit": "halted"},
        {"guardian_hold": "too good"},
        {"verdict": "KILL"},
    ],
)
def test_trouble_demotes_one_rung(trouble: dict[str, str]) -> None:
    """Issue #146: a demotion fires."""
    down = ladder.decide(_f("live_price_paper", paper_book="d1", paper_sessions=30, **trouble))
    assert down is not None and (down.to, down.action) == ("paper", "")
    off = ladder.decide(_f("paper", paper_book="d1", paper_sessions=30, **trouble))
    assert off is not None and (off.to, off.action) == ("registered", "stop_paper")


def test_the_forward_test_is_scored_once_and_only_when_it_can_be() -> None:
    base = {"paper_book": "d1", "paper_sessions": 70, "decay": "healthy"}
    reasons = ("40 trading days of 60 required",)
    early = _f("live_price_paper", **base, forward_ready=False, forward_reasons=reasons)
    assert ladder.decide(early) is None, "the one score is not spent before the sessions exist"
    won = ladder.decide(_f("live_price_paper", **base, forward_ready=True))
    assert won is not None and (won.to, won.action) == ("ready_for_real_money", "score_forward")
    lost = ladder.decide(
        _f(
            "live_price_paper",
            **base,
            forward_ready=False,
            forward_reasons=("forward Sharpe 0.20 is below 0.5 x backtest 1.80",),
        )
    )
    assert lost is not None and lost.to == "failed_forward" and "0.20" in lost.why
    again = _f("live_price_paper", **base, forward_ready=True, forward_scored=True)
    assert ladder.decide(again) is None
    assert ladder.decide(_f("failed_forward", **base, forward_ready=True)) is None
    assert ladder.decide(_f("live_price_paper", **base, forward_ready=None)) is None


def test_the_ladder_ends_at_a_list_and_a_listed_strategy_can_still_fall() -> None:
    assert ladder.decide(_f("ready_for_real_money", paper_book="d1", paper_sessions=90)) is None
    down = ladder.decide(_f("ready_for_real_money", paper_book="d1", decay="decayed"))
    assert down is not None and down.to == "live_price_paper"
    assert "live" not in " ".join(ladder.ORDER).replace("live_price_paper", "")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Three gated strategies and the facts the ladder would gather about each."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "constitution.yaml").write_text(RULES.read_text())
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    state: dict[str, Any] = {
        "H-0301": {},
        "H-0302": {"paper_book": "d2", "paper_sessions": 9, "decay": "healthy"},
        "started": [],
    }
    from eulerlab import forward

    day = date(2026, 11, 12)
    monkeypatch.setattr(
        forward,
        "verdicts",
        lambda *a, **k: {
            "H-0301": ("PROMOTE", day),
            "H-0302": ("PAPER", day),
            "H-0303": ("KILL", day),
        },
    )
    monkeypatch.setattr(
        ladder,
        "facts_for",
        lambda s, stage, verdict: _f(stage, strategy=s, verdict=verdict, **state[s]),
    )

    def start(strategy: str, today: date) -> str:
        state["started"].append(strategy)
        state[strategy] = {"paper_book": f"book-{strategy}", "paper_sessions": 0}
        return f"paper book book-{strategy}"

    monkeypatch.setattr(ladder, "start_paper", start)
    return state


def test_a_gated_strategy_reaches_live_price_paper_with_no_human_action(
    world: dict[str, Any],
) -> None:
    """Issue #146's first acceptance test, over three daily looks."""
    first = ladder.step(NOW)
    assert {(m["strategy"], m["to"]) for m in first} == {("H-0301", "paper"), ("H-0302", "paper")}
    assert world["started"] == ["H-0301"], "only the one with no book had one started"
    assert ladder.step(NOW) == [{"strategy": "H-0302", "from": "paper", "to": "live_price_paper",
                                 "why": "9 sessions on paper with no decay, loss limit or hold", "done": ""}]  # fmt: skip
    world["H-0301"]["paper_sessions"] = 5
    ladder.step(NOW)
    assert ladder.at_stage("live_price_paper") == ["H-0301", "H-0302"]
    assert "H-0303" not in ladder.stages()
    assert [r["by"] for r in ladder.moves()] == ["the ladder"] * 4
    # And from there the morning's live-price plan picks them up, with no config edit.
    from eulerlab.deploy import live_shadow

    _, skipped = live_shadow.books(Path("no-such-config.yaml"))
    assert set(skipped) == {"H-0301", "H-0302"}  # named; skipped here only because no card exists


def test_a_demotion_is_recorded_and_reaches_the_inbox(world: dict[str, Any]) -> None:
    ladder.step(NOW)
    ladder.step(NOW)
    world["H-0302"]["decay"] = "decayed"

    class Ctx:
        now = NOW

    result = ladder.worker(Ctx())
    (item,) = result.items
    assert item.title == "H-0302: live_price_paper to paper" and item.severity == "warn"
    assert "edge has gone" in item.body and not item.needs_approval
    assert ladder.stages()["H-0302"] == "paper"


def test_reaching_the_end_asks_the_operator_and_does_nothing_else(world: dict[str, Any]) -> None:
    ladder.step(NOW)
    ladder.step(NOW)
    world["H-0302"].update(paper_sessions=70, forward_ready=True)

    class Ctx:
        now = NOW

    (item,) = ladder.worker(Ctx()).items
    assert item.needs_approval and "your decision; no agent can" in item.body
    assert ladder.at_stage("ready_for_real_money") == ["H-0302"]
    from eulerlab.research import experiments

    (row,) = experiments.rows(purpose="forward")
    assert row["hypothesis"] == "H-0302" and row["metrics"]["passed"] is True


def test_the_constitution_can_stop_the_ladder_starting_books(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(strategy: str, today: date) -> str:
        raise constitution.NotAllowed("the constitution says `propose`")

    monkeypatch.setattr(ladder, "start_paper", refused)
    moves = ladder.step(NOW)
    stuck = next(m for m in moves if m["strategy"] == "H-0301")
    assert stuck["to"] == "registered" and "not deployed" in stuck["why"]
    assert "H-0301" not in ladder.stages()


# --- no agent reaches the live account ---------------------------------------------------

AGENT_SIDE = (
    "agents",
    "research",
    "deploy/ladder.py",
    "deploy/decay.py",
    "jobrun.py",
    "scorecard.py",
)
LIVE = ("eulerlab.deploy.live_money", "eulerlab.broker.smartapi", "eulerlab.broker.kite")


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out |= {node.module, *(f"{node.module}.{a.name}" for a in node.names)}
    return out


def test_no_agent_side_module_imports_the_live_order_path() -> None:
    src = Path(__file__).parents[1] / "src" / "eulerlab"
    files: list[Path] = []
    for part in AGENT_SIDE:
        target = src / part
        files += [target] if target.is_file() else sorted(target.rglob("*.py"))
    assert len(files) > 60
    guilty = {str(f.relative_to(src)): sorted(_imports(f) & set(LIVE)) for f in files}
    assert {k: v for k, v in guilty.items() if v} == {}


def test_inside_an_agent_run_every_door_to_the_live_account_is_shut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #146: no agent code path reaches the live order path or its credentials."""
    logins: list[int] = []

    def login() -> tuple[object, str]:
        logins.append(1)
        return object(), ""

    monkeypatch.setattr("eulerlab.broker.angel_check.login", login)
    settings = live_money.Settings(capital=100_000, loss_cap=2_000, leverage=1)
    with usage.asking("autopilot", "run-123"):
        with pytest.raises(constitution.NotAllowed, match="arm a live session"):
            live_money.arm(settings, "DEPLOY", root=tmp_path, tripped=lambda: False)
        with pytest.raises(constitution.NotAllowed, match="log in to the live broker"):
            live_money.AngelDesk()
        desk = object.__new__(live_money.AngelDesk)
        with pytest.raises(constitution.NotAllowed, match="send a live order"):
            desk.send("c1", date(2026, 11, 13), "AAA", True, 1)
    assert logins == [] and not list(tmp_path.rglob("*")), "nothing was armed, no login was made"
    # Outside an agent's run the operator's own path is untouched by the guard.
    constitution.refuse_agents("live_account", "arm a live session")


def test_the_constitution_cannot_be_edited_to_allow_the_live_account(tmp_path: Path) -> None:
    text = RULES.read_text().replace("live_account: never", "live_account: act")
    (tmp_path / "c.yaml").write_text(text)
    with pytest.raises(ValueError, match="can only be `never`"):
        constitution.load(tmp_path / "c.yaml")
