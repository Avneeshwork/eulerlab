"""The control room's routes and the Telegram words, against a temp agent folder.

The routes are called as functions, as the other API tests do: the suite has
no HTTP test client, and the routes hold no logic in the HTTP layer itself.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eulerlab import telegram_words
from eulerlab.agents import briefs
from eulerlab.api import agent_routes as r


def test_the_agent_list_shows_every_definition_and_a_verified_log() -> None:
    body = r.agents()
    names = {a["name"] for a in body["agents"]}
    assert {"data", "knowledge", "market_brief", "research"} <= names
    assert body["log_ok"] is True and body["inbox"] == 0


def test_switches_and_briefs_are_saved() -> None:
    assert r.agent_settings("research", r.SettingRequest(enabled=False))["enabled"] is False
    row = next(a for a in r.agents()["agents"] if a["name"] == "research")
    assert row["enabled"] is False and row["switched"] == "operator"
    assert r.agent_brief("research", r.BriefRequest(text="look at delivery"))["ok"]
    assert briefs.current("research").text == "look at delivery"  # type: ignore[union-attr]
    assert r.agent_brief("nobody", r.BriefRequest(text="x"))["ok"] is False


def test_a_budget_above_the_ceiling_is_refused_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        r.SettingRequest(daily_requests=5000)


def test_unknown_items_and_agents_are_errors_not_crashes() -> None:
    assert r.agents_decide("nope", r.DecideRequest(decision="approved"))["ok"] is False
    assert r.agent_run("nobody", r.RunRequest())["ok"] is False
    assert r.latest_brief()["ok"] is False


def test_the_log_route_reports_the_chain() -> None:
    r.agent_settings("data", r.SettingRequest(enabled=True))
    body = r.agents_log()
    assert body["verified"] is True and body["entries"][0]["kind"] == "setting"


def test_telegram_instruct_saves_a_brief_and_refuses_an_unknown_agent() -> None:
    assert "Brief saved for all" in telegram_words.instruct("all focus on banks")
    assert briefs.current("all").text == "focus on banks"  # type: ignore[union-attr]
    assert telegram_words.instruct("nobody x").startswith("No agent")
    assert telegram_words.instruct("").startswith("instruct <agent")
    assert "AGENTS" in telegram_words.agents()
    assert telegram_words.inbox_word() == "Nothing is waiting for you."


# --- the agent company's tasks (ADR-124) ------------------------------------


def test_you_give_a_head_a_task_and_it_wakes(monkeypatch: pytest.MonkeyPatch) -> None:
    woke: list[str] = []

    def wake(dept: str) -> bool:
        woke.append(dept)
        return True

    monkeypatch.setattr(r, "_wake", wake)
    made = r.agents_task_create(
        r.TaskRequest(department="research", title="Papers on low volatility")
    )
    assert (
        made["ok"] and made["task"]["owner"] == "head_research" and made["task"]["status"] == "open"
    )
    assert woke == ["research"]
    listed = r.agents_tasks()
    assert [t["id"] for t in listed["tasks"]] == [made["task"]["id"]]
    assert listed["checklist"] and listed["max_returns"] == 2


def test_a_task_for_an_unknown_department_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "_wake", lambda dept: True)
    assert r.agents_task_create(r.TaskRequest(department="sales", title="Sell more"))["ok"] is False


def test_your_actions_on_a_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.agents import tasks

    monkeypatch.setattr(r, "_wake", lambda dept: True)
    tid = r.agents_task_create(r.TaskRequest(department="research", title="Look into quality"))[
        "task"
    ]["id"]
    assert r.agents_task_act(tid, r.TaskAction(action="close"))["ok"] is False  # not done yet
    assert r.agents_task_act(tid, r.TaskAction(action="send_back"))["ok"] is False
    assert (
        r.agents_task_act(tid, r.TaskAction(action="run"))["ok"] is False
    )  # a head's task is not run
    lab = tasks.create(
        title="Test card",
        owner="lab",
        department="research",
        created_by="head_research",
        kind="test_card",
        args={"card": "hypotheses/c1"},
    )
    refused = r.agents_task_act(lab.id, r.TaskAction(action="run"))
    assert refused["ok"] is False and "make agent NAME=lab" in refused["error"]
    assert r.agents_task_act(tid, r.TaskAction(action="cancel"))["task"]["status"] == "cancelled"
    assert r.agents_task_act(tid, r.TaskAction(action="retry"))["task"]["status"] == "open"
    assert r.agents_task_act("T-none", r.TaskAction(action="close"))["ok"] is False


def test_plans_and_capabilities_are_served() -> None:
    plans = r.agents_plans_today()["plans"]
    assert {"head_research", "data", "lab"} <= set(plans)
    assert plans["data"]["duties"]
    caps = r.agents_capabilities()
    assert caps["ok"] and caps["gaps"] == []


def test_the_org_chart_shows_heads_as_running_people() -> None:
    chart = r.agents_org()
    assert chart["ok"] and chart["problems"] == []
    heads = [d["head"] for d in chart["departments"]]
    assert all(h["running"] and h["duties"] for h in heads)
    names = {a["name"] for d in chart["departments"] for a in d["agents"]}
    assert not any(n.startswith("head_") for n in names)


def test_you_can_ask_ai_help_for_a_blocked_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.agents import tasks

    woke: list[str] = []

    def wake(dept: str) -> bool:
        woke.append(dept)
        return True

    monkeypatch.setattr(r, "_wake", wake)
    t = tasks.create(
        title="Look", owner="research", department="research", created_by="head_research"
    )
    assert r.agents_task_act(t.id, r.TaskAction(action="assist"))["ok"] is False  # not stuck
    tasks.record(t.id, "blocked", "head_research", {"note": "refused"})
    done = r.agents_task_act(t.id, r.TaskAction(action="assist"))
    assert done["ok"] and done["asked"] == [t.id] and woke == ["research"]
    assert tasks.load()[t.id].help_wanted is True
