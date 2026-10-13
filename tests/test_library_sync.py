"""Research papers coded as studies appear in the library with their results.

Operator, 2026-10-12: "get all papers in research and update in strategy
library".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import eulerlab.research.library_sync as library_sync
import eulerlab.results as result_store
import eulerlab.workspace as workspace_mod
from eulerlab.api import research_routes
from eulerlab.research import library
from eulerlab.strategies import REGISTRY, studies


def test_every_study_is_in_the_library_and_says_where_it_came_from() -> None:
    assert len(studies.ENTRIES) == len(studies.IDS) == 9
    for entry in studies.ENTRIES:
        declared = REGISTRY[entry["id"]]
        assert declared.is_strategy_subclass is False, "none can run in an engine"
        assert declared.source and declared.published and declared.tested_on
        assert declared.source.startswith(("[paper] ", "[practitioner] "))
        assert Path(entry["research"]).name[:3].isdigit()
        assert studies.COMMANDS[entry["study"]] in declared.logic[-1]
        assert entry["configurations"], "a study with nothing to show"


def test_no_study_takes_an_id_another_strategy_has() -> None:
    from eulerlab.api import server

    assert not studies.IDS & server.INTRADAY_RUNNABLE
    assert not studies.IDS & server.STUDY_RUNNABLE
    others = [d.id for d in REGISTRY.values()]
    assert len(others) == len(set(others))


def _intraday(rules: list[str]) -> dict[str, Any]:
    return {
        "window": ["2021-08-20", "2026-10-12"],
        "universe": ["AAA", "BBB"],
        "runs": [
            {
                "rule": rule,
                "net": {
                    "sharpe": -1.0 - i,
                    "total_return": -0.2,
                    "max_drawdown": -0.25,
                    "trades": 10,
                    "days": 3,
                },
                "daily": [["2026-10-08", 0.01], ["2026-10-09", -0.02], ["2026-10-12", 0.0]],
            }
            for i, rule in enumerate(rules)
        ],
    }


@pytest.fixture
def tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    real = workspace_mod.resolve(None)
    fake = type("W", (), {"results": tmp_path / "results", "ledger": real.ledger})()
    monkeypatch.setattr(workspace_mod, "resolve", lambda principal=None: fake)
    return fake


def test_each_published_setting_is_stored_once_and_the_main_one_last(
    tmp_path: Path, tenant: Any
) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "late_opening_range")
    names = list(entry["configurations"].values())
    (tmp_path / "india_intraday_papers.json").write_text(json.dumps(_intraday(names)))

    report = library_sync.sync(tmp_path)
    assert report["late_opening_range"] == (2, 0)
    assert report["gao_last_half_hour"] == (0, 0), "its study has not been run here"

    stored = result_store.distinct(tenant, "late_opening_range")
    assert len(stored) == 2 and {r.tier for r in stored} == {"study"}
    assert {r.universe for r in stored} == {
        "NIFTYBEES: range to 10:15",
        "NIFTYBEES: range to 11:15",
    }
    latest = result_store.latest(tenant, "late_opening_range", stored)
    assert latest is not None and latest.params["rule"] == names[-1]
    assert latest.fills == 20 and latest.days == 3 and latest.trial_recorded is False
    assert latest.curve == [1_000_000.0, 1_010_000.0, 989_800.0, 989_800.0]
    assert result_store.summary(tenant, "late_opening_range")["runs"] == 2

    assert library_sync.sync(tmp_path)["late_opening_range"] == (0, 2), "a second run adds nothing"
    assert len(result_store.distinct(tenant, "late_opening_range")) == 2


def test_new_data_is_a_new_result_not_a_repeat(tmp_path: Path, tenant: Any) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "rest_of_day_momentum")
    payload = _intraday(list(entry["configurations"].values()))
    path = tmp_path / "india_intraday_papers.json"
    path.write_text(json.dumps(payload))
    library_sync.sync(tmp_path)
    payload["window"][1] = "2026-11-30"
    path.write_text(json.dumps(payload))
    assert library_sync.sync(tmp_path)["rest_of_day_momentum"] == (1, 0)


def test_a_stock_study_records_how_many_stocks_and_a_missing_setting_is_skipped(
    tmp_path: Path, tenant: Any
) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "extreme_move_fade")
    names = list(entry["configurations"].values())
    (tmp_path / "india_intraday_papers.json").write_text(json.dumps(_intraday(names[:3])))
    assert library_sync.sync(tmp_path)["extreme_move_fade"] == (3, 0)
    assert {r.symbols for r in result_store.distinct(tenant, "extreme_move_fade")} == {2}


def test_an_options_study_is_read_by_name_with_a_point_per_period(
    tmp_path: Path, tenant: Any
) -> None:
    payload = {
        "window": ["2015-01-01", "2026-10-07"],
        "runs": [
            {
                "name": name,
                "whole": {"periods": 2, "sharpe": 0.4, "total_return": 0.1, "max_drawdown": -0.3},
                "periods": [["2015-01-30", "2015-02-26", 0.1, 1.0, "x"], ["a", "b", 0.0, 1.0, "y"]],
            }
            for name in ("short_strangle_leg1", "short_strangle_leg2", "short_strangle_leg3")
        ],
    }
    (tmp_path / "options_strategies.json").write_text(json.dumps(payload))
    assert library_sync.sync(tmp_path)["nifty_short_strangle"] == (3, 0)
    assert library_sync.sync(tmp_path)["nifty_covered_call"] == (0, 0)
    run = result_store.latest(tenant, "nifty_short_strangle")
    assert run is not None and run.asset_class == "options" and run.days == 2
    assert run.curve == [1_000_000.0, 1_100_000.0, 1_100_000.0]


def test_every_study_is_linked_from_a_paper_in_the_research_library() -> None:
    linked = {
        link.id
        for paper in library.all_papers(root=Path("research/papers"))
        for link in paper.strategies
        if link.kind == "registered"
    }
    assert linked >= studies.IDS


def test_a_study_linked_from_a_paper_offers_no_backtest_button() -> None:
    tenant = workspace_mod.resolve(None)
    study = research_routes._link_view(
        tenant, library.StrategyLink(kind="registered", id="late_opening_range")
    )
    engine = research_routes._link_view(
        tenant, library.StrategyLink(kind="registered", id="momentum_12_1")
    )
    assert study["exists"] is True
    assert study["runnable"] is False
    assert engine["runnable"] is True
