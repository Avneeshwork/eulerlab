"""Model cutoffs (ADR-176): judged values are stamped, pre-cutoff backtests refused, recall probed."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.intraday import rule_engine as engine
from eulerlab.llm import cutoff
from eulerlab.research import fast_eval, lang
from test_lang_fast_eval import _market


def test_the_four_current_claude_models_have_a_published_cutoff() -> None:
    found = cutoff.cutoffs()
    assert found["claude-sonnet-5-5"] == date(2026, 6, 30)
    assert cutoff.cutoff("openai/gpt-oss-120b") is None


def test_a_window_on_or_before_the_cutoff_is_refused() -> None:
    with pytest.raises(cutoff.BeforeCutoff, match="trained on data up to 2026-06-30"):
        cutoff.require_after("claude-sonnet-5-5", date(2026, 6, 30))
    cutoff.require_after("claude-sonnet-5-5", date(2026, 7, 1))
    with pytest.raises(cutoff.BeforeCutoff, match="no published training cutoff"):
        cutoff.require_after("openai/gpt-oss-120b", date(2026, 11, 1))


def test_a_judged_value_is_stamped_with_its_model_and_cutoff(tmp_path: Path) -> None:
    path = tmp_path / "v.jsonl"
    now = datetime(2026, 11, 13, 4, tzinfo=UTC)
    cutoff.stamp(
        "news_impact", 0.25, "claude-haiku-5-5", about=date(2026, 11, 13), now=now, path=path
    )
    cutoff.stamp("news_impact", -0.5, "local", about=date(2026, 11, 14), now=now, path=path)
    first, second = cutoff.stamped("news_impact", path)
    assert (first["model"], first["cutoff"], second["cutoff"]) == (
        "claude-haiku-5-5", "2026-06-30", None,
    )  # fmt: skip
    values, models = cutoff.series("news_impact", path)
    assert values == {date(2026, 11, 13): 0.25, date(2026, 11, 14): -0.5}
    assert models == {"claude-haiku-5-5", "local"}


def test_the_evaluator_refuses_a_pre_cutoff_window_for_a_news_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #141's acceptance test."""
    monkeypatch.setattr(engine.Engine, "short", frozenset())
    data = _market()
    data.__dict__["mornings"] = frozenset()
    day = data.sessions[30]
    store = fast_eval.Store(
        engine.Engine(data),
        market={"news_impact": {day: 1.0}},
        judged_by={"news_impact": {"claude-sonnet-5-5"}},
    )
    fast = fast_eval.FastEngine(data, store)
    body = {
        "shape": "event",
        "kind": "intraday",
        "when": "gt(delay(news_impact, 1), 0)",
        "score": "neg(abs(gap))",
    }
    with pytest.raises(cutoff.BeforeCutoff, match="news_impact"):
        fast.events(lang.Spec(**body, first=data.sessions[0]))  # 2022: before the cutoff
    # The same rule on a window after the cutoff is allowed (it has no sessions here).
    assert fast.events(lang.Spec(**body, first=date(2026, 7, 1))) == []
    # A rule that reads no judged field is not touched by the check.
    assert fast.events(lang.Spec(**{**body, "when": "gt(gap, 0)"}, first=data.sessions[0]))


def test_the_probe_scores_recall_by_month_and_flags_recall_past_the_cutoff(tmp_path: Path) -> None:
    start = date(2026, 1, 1)
    truth = {start + timedelta(days=i): 25000.0 + i for i in range(300)}

    named = {d.strftime("%d %B %Y"): d for d in truth}

    def ask(question: str) -> str:
        # Recalls everything to the end of August, two months past the published cutoff.
        day = named[question.split(" on ")[1].split("?")[0]]
        return f"{truth[day]:,.0f}" if day <= date(2026, 8, 31) else "unknown"

    report = cutoff.probe("claude-sonnet-5-5", ask, truth, count=10, out_dir=tmp_path)
    assert report["published_cutoff"] == "2026-06-30"
    assert report["last_month_recalled"] == "2026-08"
    assert report["recalled_after_cutoff"] == ["2026-07", "2026-08"]
    assert report["months"]["2026-10"] == {"asked": 1, "recalled": 0}
    assert "RECALLS MONTHS AFTER" in cutoff.render(report)
    assert (tmp_path / "claude-sonnet-5-5.json").exists()
