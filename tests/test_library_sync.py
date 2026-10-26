"""Research papers coded as studies appear in the library with their results.

Operator, 2026-10-12: "get all papers in research and update in strategy
library".
"""

from __future__ import annotations

import json
from dataclasses import replace
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
    assert len(studies.ENTRIES) == len(studies.IDS) == 48
    for entry in studies.ENTRIES:
        declared = REGISTRY[entry["id"]]
        assert declared.is_strategy_subclass is False, "none can run in an engine"
        assert declared.source and declared.published and declared.tested_on
        assert declared.source.startswith(("[paper] ", "[practitioner] ", "[GitHub] "))
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


def test_mcx_gold_result_uses_one_lot_daily_pnl_and_is_net_of_costs() -> None:
    payload = {
        "starting_contract_notional_rupees": 10_000_000,
        "fills": 12,
        "net": {
            "sessions": 2,
            "daily_sharpe": -1.25,
            "return_on_initial_contract_notional": -0.03,
            "max_drawdown_on_initial_contract_notional": -0.04,
            "daily": [["2026-10-13", -100_000], ["2026-10-14", -200_000]],
        },
    }
    name = "SMA(50), 20 bp dead band, MCX Gold"

    measured = library_sync.measured(studies.MCX_GOLD_BACKTEST, payload, name)

    assert measured is not None
    assert measured["total_return"] == -0.03
    assert measured["sharpe"] == -1.25
    assert measured["fills"] == 12
    assert measured["days"] == 2
    assert measured["curve"][0] == 1_000_000
    assert measured["curve"][-1] == 970_000


def test_new_stock_candidate_result_is_imported_with_its_costed_curve() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_intraday_pair_convergence")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 8,
                "daily": [["2024-01-02", 0.01], ["2024-01-03", -0.02]],
                "net": {"days": 2, "sharpe": -0.5, "total_return": -0.0102, "max_drawdown": -0.02},
            }
        ]
    }

    measured = library_sync.measured(studies.STOCK_CANDIDATES, payload, rule)

    assert measured is not None
    assert measured["fills"] == 8
    assert measured["days"] == 2
    assert measured["total_return"] == -0.0102
    assert measured["curve"] == [1_000_000.0, 1_010_000.0, 989_800.0]


def test_github_followup_result_is_imported_with_costed_daily_curve() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_ema_macd_swing_pullback")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 4,
                "daily": [["2024-01-02", 0.01], ["2024-01-03", -0.02]],
                "net": {"days": 2, "sharpe": -0.5, "total_return": -0.0102, "max_drawdown": -0.02},
            }
        ]
    }

    measured = library_sync.measured(studies.GITHUB_FOLLOWUP, payload, rule)

    assert measured is not None
    assert measured["fills"] == 4
    assert measured["days"] == 2
    assert measured["total_return"] == -0.0102
    assert measured["curve"] == [1_000_000.0, 1_010_000.0, 989_800.0]


def test_github_momentum_pullback_result_is_imported() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_surge_pullback_new_high")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 2,
                "daily": [["2024-01-02", 0.001]],
                "net": {"days": 1, "sharpe": 0.2, "total_return": 0.001, "max_drawdown": 0.0},
            }
        ]
    }

    measured = library_sync.measured(studies.GITHUB_MOMENTUM_PULLBACK, payload, rule)

    assert measured is not None
    assert measured["fills"] == 2
    assert measured["total_return"] == 0.001


def test_inside_bar_result_is_imported_with_costed_daily_curve() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_inside_bar_breakout_2r")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 4,
                "daily": [["2024-01-02", 0.01], ["2024-01-03", -0.02]],
                "net": {"days": 2, "sharpe": -0.5, "total_return": -0.0102, "max_drawdown": -0.02},
            }
        ]
    }

    measured = library_sync.measured(studies.INSIDE_BAR, payload, rule)

    assert measured is not None
    assert measured["fills"] == 4
    assert measured["days"] == 2
    assert measured["total_return"] == -0.0102
    assert measured["curve"] == [1_000_000.0, 1_010_000.0, 989_800.0]


def test_hikkake_result_is_imported_with_costed_daily_curve() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_hikkake_failed_inside_bar")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 2,
                "daily": [["2024-01-02", -0.01]],
                "net": {"days": 1, "sharpe": -0.2, "total_return": -0.01, "max_drawdown": -0.01},
            }
        ]
    }

    measured = library_sync.measured(studies.HIKKAKE, payload, rule)

    assert measured is not None
    assert measured["fills"] == 2
    assert measured["days"] == 1
    assert measured["total_return"] == -0.01
    assert measured["curve"] == [1_000_000.0, 990_000.0]


def test_github_ema_result_is_imported_with_costed_daily_curve() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_github_ema_5_15_crossover")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 6,
                "daily": [["2024-01-02", 0.005], ["2024-01-03", -0.002]],
                "net": {"days": 2, "sharpe": 0.1, "total_return": 0.00299, "max_drawdown": -0.002},
            }
        ]
    }

    measured = library_sync.measured(studies.GITHUB_EMA, payload, rule)

    assert measured is not None
    assert measured["fills"] == 6
    assert measured["days"] == 2
    assert measured["total_return"] == 0.00299
    assert measured["curve"] == [1_000_000.0, 1_005_000.0, 1_002_990.0]


def test_supertrend_alignment_result_is_imported_with_costed_daily_curve() -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_supertrend_mtf_volume_reclaim")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "runs": [
            {
                "id": rule,
                "fills": 4,
                "daily": [["2024-01-02", 0.01]],
                "net": {"days": 1, "sharpe": 0.0, "total_return": 0.01, "max_drawdown": 0.0},
            }
        ]
    }

    measured = library_sync.measured(studies.SUPERTREND_MTF, payload, rule)

    assert measured is not None
    assert measured["fills"] == 4
    assert measured["days"] == 1
    assert measured["total_return"] == 0.01
    assert measured["curve"] == [1_000_000.0, 1_010_000.0]


def test_trial_link_metadata_repairs_an_already_stored_stock_candidate(
    tmp_path: Path, tenant: Any
) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "nse_intraday_pair_convergence")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": rule,
                "fills": 8,
                "daily": [["2024-01-02", 0.01]],
                "net": {"days": 1, "sharpe": 0.0, "total_return": 0.01, "max_drawdown": 0.0},
            }
        ],
    }
    expected = library_sync.runs_for(entry, payload)[0]
    result_store.record(tenant, replace(expected, trial_recorded=False))
    (tmp_path / "stock_intraday_candidates.json").write_text(json.dumps(payload))

    assert library_sync.sync(tmp_path)[entry["id"]] == (1, 0)
    stored = result_store.distinct(tenant, entry["id"])
    assert len(stored) == 1 and stored[0].trial_recorded is True
    assert library_sync.sync(tmp_path)[entry["id"]] == (0, 1)


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


def test_lagged_fii_positioning_result_is_imported_as_five_stock_study(
    tmp_path: Path, tenant: Any
) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "fii_index_futures_position_follow")
    rule = next(iter(entry["configurations"].values()))
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS"],
        "result": {
            "fills": 10,
            "daily": [["2024-01-03", 0.01], ["2024-01-04", -0.02]],
            "net": {"days": 2, "sharpe": -0.5, "total_return": -0.0102, "max_drawdown": -0.02},
        },
    }
    measured = library_sync.measured(studies.FII_PARTICIPANT_OI, payload, rule)
    assert measured is not None
    assert measured["fills"] == 10 and measured["total_return"] == -0.0102
    (tmp_path / f"{studies.FII_PARTICIPANT_OI}.json").write_text(json.dumps(payload))
    assert library_sync.sync(tmp_path)[entry["id"]] == (1, 0)
    stored = result_store.distinct(tenant, entry["id"])
    assert len(stored) == 1 and stored[0].symbols == 5


def test_github_keltner_result_is_imported_from_screen_output() -> None:
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": "nse_github_keltner_channel_breakout",
                "net": {"sharpe": -1.25, "total_return": -0.02, "max_drawdown": -0.03, "days": 10},
                "fills": 24,
                "daily": [["2024-01-01", -0.001]],
            }
        ],
    }
    measured = library_sync.measured(
        studies.GITHUB_KELTNER, payload, "nse_github_keltner_channel_breakout"
    )
    assert measured == {
        "sharpe": -1.25,
        "total_return": -0.02,
        "max_drawdown": -0.03,
        "fills": 24,
        "days": 10,
        "curve": [1_000_000.0, 999_000.0],
    }


def test_github_donchian_result_is_imported_from_screen_output() -> None:
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": "nse_github_donchian_breakout",
                "net": {"sharpe": -0.75, "total_return": -0.01, "max_drawdown": -0.02, "days": 10},
                "fills": 20,
                "daily": [["2024-01-01", -0.001]],
            }
        ],
    }
    measured = library_sync.measured(
        studies.GITHUB_DONCHIAN, payload, "nse_github_donchian_breakout"
    )
    assert measured is not None and measured["fills"] == 20
    assert measured["total_return"] == -0.01


def test_github_pivot_result_is_imported_from_screen_output() -> None:
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": "nse_github_prior_day_pivot_breakout",
                "net": {"sharpe": -0.25, "total_return": -0.005, "max_drawdown": -0.01, "days": 10},
                "fills": 12,
                "daily": [["2024-01-01", -0.0005]],
            }
        ],
    }
    measured = library_sync.measured(
        studies.GITHUB_PIVOT, payload, "nse_github_prior_day_pivot_breakout"
    )
    assert measured is not None and measured["fills"] == 12
    assert measured["total_return"] == -0.005


def test_github_engulfing_result_is_imported_from_screen_output() -> None:
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": "nse_github_engulfing_volume_rsi",
                "net": {"sharpe": -0.5, "total_return": -0.01, "max_drawdown": -0.02, "days": 10},
                "fills": 8,
                "daily": [["2024-01-01", -0.001]],
            }
        ],
    }
    measured = library_sync.measured(
        studies.GITHUB_ENGULFING, payload, "nse_github_engulfing_volume_rsi"
    )
    assert measured is not None and measured["fills"] == 8
    assert measured["total_return"] == -0.01


def test_github_momentum_burst_result_is_imported_from_screen_output() -> None:
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": "nse_github_3bar_atr_momentum_burst",
                "net": {"sharpe": 0.4, "total_return": 0.01, "max_drawdown": -0.02, "days": 10},
                "fills": 14,
                "daily": [["2024-01-01", 0.001]],
            }
        ],
    }
    measured = library_sync.measured(
        studies.GITHUB_MOMENTUM_BURST, payload, "nse_github_3bar_atr_momentum_burst"
    )
    assert measured is not None and measured["fills"] == 14
    assert measured["total_return"] == 0.01


def test_github_rsi2_result_is_imported_from_screen_output() -> None:
    payload = {
        "window": ["2024-01-01", "2024-11-30"],
        "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY"],
        "runs": [
            {
                "id": "nse_github_connors_rsi2_intraday_pullback",
                "net": {"sharpe": -0.3, "total_return": -0.02, "max_drawdown": -0.03, "days": 10},
                "fills": 16,
                "daily": [["2024-01-01", -0.002]],
            }
        ],
    }
    measured = library_sync.measured(
        studies.GITHUB_RSI2, payload, "nse_github_connors_rsi2_intraday_pullback"
    )
    assert measured is not None and measured["fills"] == 16
    assert measured["total_return"] == -0.02


def test_new_data_is_a_new_result_not_a_repeat(tmp_path: Path, tenant: Any) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "rest_of_day_momentum")
    payload = _intraday(list(entry["configurations"].values()))
    path = tmp_path / "india_intraday_papers.json"
    path.write_text(json.dumps(payload))
    library_sync.sync(tmp_path)
    payload["window"][1] = "2026-11-30"
    path.write_text(json.dumps(payload))
    assert library_sync.sync(tmp_path)["rest_of_day_momentum"] == (1, 0)


def test_recomputed_result_replaces_measurement_for_same_configuration(
    tmp_path: Path, tenant: Any
) -> None:
    entry = next(e for e in studies.ENTRIES if e["id"] == "late_opening_range")
    names = list(entry["configurations"].values())
    payload = _intraday(names)
    path = tmp_path / "india_intraday_papers.json"
    path.write_text(json.dumps(payload))
    assert library_sync.sync(tmp_path)[entry["id"]] == (2, 0)

    payload["runs"][0]["net"]["total_return"] = -0.25
    path.write_text(json.dumps(payload))
    assert library_sync.sync(tmp_path)[entry["id"]] == (1, 1)
    stored = result_store.distinct(tenant, entry["id"])
    assert len(stored) == 2
    changed = next(run for run in stored if run.params["rule"] == names[0])
    assert changed.total_return == -0.25


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


def test_gold_and_stock_screen_results_sync_into_the_research_library(
    tmp_path: Path, tenant: Any
) -> None:
    gold = next(e for e in studies.ENTRIES if e["id"] == "gold_intraday_ma_rules")
    stock = next(e for e in studies.ENTRIES if e["id"] == "extreme_minute_reversal")
    tree = next(e for e in studies.ENTRIES if e["id"] == "nse_minute_decision_tree")
    gold_rule = next(iter(gold["configurations"].values()))
    payload = {
        "window": ["2021-08-20", "2024-11-29"],
        "gold_runs": [
            {
                "rule": gold_rule,
                "fills": 100,
                "evaluation_2024_through_2024_11_30": {
                    "sharpe": -1.2,
                    "total_return": -0.1,
                    "max_drawdown": -0.12,
                    "days": 2,
                },
                "daily": [["2023-12-29", 0.5], ["2024-01-02", -0.05], ["2024-01-03", -0.05]],
            }
        ],
        "stock_run": {
            "rule": next(iter(stock["configurations"].values())),
            "events": 2,
            "net": {
                "sharpe": -2.0,
                "total_return": -0.03,
                "max_drawdown": -0.04,
                "days": 2,
            },
            "daily": [["2024-01-02", -0.01], ["2024-01-03", -0.02]],
        },
        "stock_tree_run": {
            "rule": next(iter(tree["configurations"].values())),
            "events": 2,
            "net": {
                "sharpe": -3.0,
                "total_return": -1.0,
                "max_drawdown": -1.0,
                "days": 2,
            },
            "daily": [["2024-01-02", -0.5], ["2024-01-03", -0.5]],
        },
    }
    (tmp_path / "gold_stock_intraday_screen.json").write_text(json.dumps(payload))

    report = library_sync.sync(tmp_path)

    assert report["gold_intraday_ma_rules"] == (1, 0)
    assert report["extreme_minute_reversal"] == (1, 0)
    assert report["nse_minute_decision_tree"] == (1, 0)
    stored = result_store.latest(tenant, "gold_intraday_ma_rules")
    assert stored is not None and stored.curve == [
        1_000_000.0,
        950_000.0,
        902_500.0,
    ]


def test_every_study_is_linked_from_a_paper_in_the_research_library() -> None:
    linked = {
        link.id
        for paper in library.all_papers(root=Path("research/papers"))
        for link in paper.strategies
        if link.kind == "registered"
    }
    assert linked >= studies.IDS


def test_company_github_price_candidate_results_are_syncable() -> None:
    payload = {
        "runs": [
            {
                "id": "nse_bollinger_squeeze_expansion",
                "net": {"sharpe": -1.0, "total_return": -0.1, "max_drawdown": -0.12, "days": 10},
                "fills": 20,
                "daily": [["2024-01-02", -0.01]],
            }
        ]
    }

    result = library_sync.measured(
        studies.COMPANY_GITHUB, payload, "nse_bollinger_squeeze_expansion"
    )

    assert result is not None
    assert result["total_return"] == -0.1
    assert result["fills"] == 20


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


def test_a_paper_draft_accepts_the_shapes_small_models_answer_in() -> None:
    from eulerlab.api.research_routes import PaperDraft

    reply = """Here you go:
```json
{"summary": "s", "trade_idea": "t",
 "implementation": {"universe": "unspecified", "costs": "before costs"},
 "red_flags": "Not stated in the supplied text.", "reported_results": ["r1", "r2"],
 "markets": "US equities"}
```"""
    draft = PaperDraft.parse(reply)
    assert draft.implementation == "universe: unspecified\ncosts: before costs"
    assert draft.red_flags == ["Not stated in the supplied text."]
    assert draft.reported_results == "r1\nr2" and draft.markets == ["US equities"]
