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
