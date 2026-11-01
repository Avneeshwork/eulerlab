"""The search bar (ADR-108): families with measured spread, and Romano-Wolf over Nifty."""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.validation import search_bar as sb
from eulerlab.validation.statistics import expected_max_sharpe

DAYS = [date(2018, 1, 1) + timedelta(days=i) for i in range(1000)]
RULES = {
    "family_join_correlation": 0.7,
    "romano_wolf_alpha": 0.05,
    "romano_wolf_block_days": 10,
    "romano_wolf_draws": 300,
}


def _series(seed: int, drift: float = 0.0, base: list[float] | None = None) -> dict[date, float]:
    rng = random.Random(seed)
    values = [rng.gauss(drift, 0.01) for _ in DAYS]
    if base is not None:
        values = [b + 0.2 * v for b, v in zip(base, values, strict=True)]
    return dict(zip(DAYS, values, strict=True))


def test_copies_of_one_idea_count_as_one_family() -> None:
    base = list(_series(1).values())
    copies = [_series(10 + k, base=base) for k in range(6)]
    others = [_series(100 + k) for k in range(3)]
    bar = sb.family_bar([*copies, *others], join_at=0.7)
    assert bar is not None
    assert bar.strategies == 9
    assert bar.families == 4
    assert bar.bar == pytest.approx(
        expected_max_sharpe(4, variance_of_sharpes=bar.sigma**2), abs=1e-3
    )


def test_ten_more_copies_do_not_raise_the_bar_the_way_ten_new_ideas_do() -> None:
    base = list(_series(1).values())
    start = [_series(100 + k) for k in range(4)]
    copies = [_series(10 + k, base=base) for k in range(10)]
    new = [_series(200 + k) for k in range(10)]
    with_copies = sb.family_bar([*start, *copies], join_at=0.7)
    with_new = sb.family_bar([*start, *new], join_at=0.7)
    assert with_copies is not None and with_new is not None
    assert with_copies.families == 5
    assert with_new.families == 14


def test_too_little_to_cluster_is_none() -> None:
    assert sb.family_bar([_series(1)], join_at=0.7) is None


def test_romano_wolf_passes_a_real_edge_over_the_market() -> None:
    market = _series(0)
    edge = {d: market[d] + 0.003 + e for d, e in _series(5).items()}
    noise = [{d: market[d] + e for d, e in _series(50 + k).items()} for k in range(8)]
    result = sb.romano_wolf(edge, noise, market, alpha=0.05, block_days=10, draws=300)
    assert result is not None
    assert result.passed
    assert result.candidate_sharpe > result.critical_sharpe
    assert result.strategies == 9


def test_romano_wolf_fails_the_luckiest_of_many_noise_strategies() -> None:
    market = _series(0)
    noise = [{d: market[d] + e for d, e in _series(50 + k).items()} for k in range(30)]
    best = max(noise, key=lambda s: sum(s[d] - market[d] for d in DAYS))
    rest = [s for s in noise if s is not best]
    result = sb.romano_wolf(best, rest, market, alpha=0.05, block_days=10, draws=300)
    assert result is not None
    assert not result.passed


def test_romano_wolf_is_deterministic() -> None:
    market = _series(0)
    cand = {d: market[d] + 0.001 + e for d, e in _series(5).items()}
    others = [_series(60 + k) for k in range(4)]
    first = sb.romano_wolf(cand, others, market, alpha=0.05, block_days=10, draws=200)
    second = sb.romano_wolf(cand, others, market, alpha=0.05, block_days=10, draws=200)
    assert first == second


def test_strategies_without_the_candidates_window_are_left_out() -> None:
    market = _series(0)
    cand = _series(5, drift=0.002)
    short = dict(list(_series(7).items())[:100])
    result = sb.romano_wolf(cand, [short], market, alpha=0.05, block_days=10, draws=100)
    assert result is not None
    assert result.strategies == 1
    assert result.days == len(DAYS)


def test_assess_builds_the_pack_block() -> None:
    market = _series(0)
    universe = [_series(100 + k) for k in range(5)]
    cand = _series(5, drift=0.002)
    block = sb.assess(cand, [_series(6)], RULES, universe=universe, market=market)
    assert block["method"] == "families"
    assert block["strategies_seen"] == 7
    assert block["romano_wolf"]["alpha"] == 0.05


def test_assess_without_stored_strategies_has_no_method() -> None:
    block = sb.assess(_series(5), [], RULES, universe=[], market={})
    assert block["method"] is None
    assert "romano_wolf" not in block


# --- the bar the workbench shows is the gate's (HISTORY #50) -------------------


def _store(root: Path, strategy: str, returns: dict[date, float]) -> None:
    import json

    values, level = [100.0], 100.0
    for r in returns.values():
        level *= 1.0 + r
        values.append(level)
    days = [(DAYS[0] - timedelta(days=1)).isoformat(), *(d.isoformat() for d in returns)]
    folder = root / "default" / "reports" / strategy
    folder.mkdir(parents=True, exist_ok=True)
    report = {
        "strategy_id": strategy,
        "configuration": "base",
        "equity": {"days": days, "values": values},
    }
    (folder / "base.json").write_text(json.dumps(report), encoding="utf-8")


def test_the_shown_bar_is_the_family_bar_over_stored_reports(tmp_path: Path) -> None:
    series = [_series(200 + k, drift=0.0004 * k) for k in range(4)]
    for k, s in enumerate(series):
        _store(tmp_path, f"s{k}", s)
    shown = sb.shown_bar(RULES, ledger_bar=9.99, root=tmp_path)
    assert shown.families is not None
    expected = sb.family_bar(sb.stored_universe(tmp_path), join_at=0.7)
    assert expected is not None
    assert shown.value == expected.bar
    assert shown.families.strategies == 4
    assert "idea families" in shown.basis


def test_without_stored_reports_the_shown_bar_falls_back_to_the_ledger(tmp_path: Path) -> None:
    shown = sb.shown_bar(RULES, ledger_bar=1.88, root=tmp_path)
    assert shown.families is None
    assert shown.value == 1.88
    assert "trial count" in shown.basis


def test_a_new_report_refreshes_the_cached_bar(tmp_path: Path) -> None:
    for k in range(3):
        _store(tmp_path, f"s{k}", _series(300 + k))
    first = sb.stored_family_bar(join_at=0.7, root=tmp_path)
    _store(tmp_path, "s3", _series(303, drift=0.002))
    second = sb.stored_family_bar(join_at=0.7, root=tmp_path)
    assert first is not None and second is not None
    assert (first.strategies, second.strategies) == (3, 4)


def test_the_forecast_assumes_every_new_configuration_is_a_new_family() -> None:
    bar = sb.FamilyBar(strategies=30, families=10, sigma=0.5, bar=0.0)
    assert sb.bar_if_new(bar, 5) == pytest.approx(expected_max_sharpe(15, variance_of_sharpes=0.25))
    assert sb.bar_if_new(bar, 0) == pytest.approx(expected_max_sharpe(10, variance_of_sharpes=0.25))
