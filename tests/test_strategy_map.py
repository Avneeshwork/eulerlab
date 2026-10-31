"""The strategy map (ADR-101): correlations, families, independent bets, one fixed book."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.research import strategy_map as sm

DAYS = [date(2018, 1, 1) + timedelta(days=i) for i in range(800)]


def _noise(seed: int, n: int = len(DAYS)) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, 0.01) for _ in range(n)]


def _series(returns: list[float], days: list[date] = DAYS) -> dict[date, float]:
    return dict(zip(days, returns, strict=True))


def _write_report(
    root: Path, strategy: str, config: str, returns: list[float], **extra: object
) -> None:
    values = [100_000.0]
    for r in returns:
        values.append(values[-1] * (1 + r))
    days = [DAYS[0] - timedelta(days=1), *DAYS[: len(returns)]]
    path = root / "default" / "reports" / strategy / f"{config}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy_id": strategy,
        "configuration": config,
        "asset_class": "equity",
        "equity": {"days": [d.isoformat() for d in days], "values": values},
        **extra,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_returns_come_back_from_the_stored_curve(tmp_path: Path) -> None:
    rets = _noise(1)
    _write_report(tmp_path, "a", "c1", rets)
    [series] = sm.collect(tmp_path)
    got = [series.returns[d] for d in DAYS]
    assert got == pytest.approx(rets, abs=1e-9)


def test_collect_keeps_the_longest_configuration_and_skips_runs_short_flat_and_other_assets(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path, "a", "short", _noise(1, 600))
    _write_report(tmp_path, "a", "long", _noise(2, 700))
    _write_report(tmp_path, "tiny", "c", _noise(3, 100))
    _write_report(tmp_path, "flat", "c", [0.0] * 700)
    _write_report(tmp_path, "fx", "c", _noise(4, 700), asset_class="fx")
    run_copy = tmp_path / "default" / "reports" / "a" / "runs" / "long" / "x.json"
    run_copy.parent.mkdir(parents=True)
    run_copy.write_text("{}", encoding="utf-8")
    found = sm.collect(tmp_path)
    assert [(s.strategy_id, s.configuration) for s in found] == [("a", "long")]


def test_correlation_needs_enough_shared_days() -> None:
    a = _series(_noise(1))
    b = dict(list(_series(_noise(2)).items())[:100])
    assert sm.correlation(a, b) is None
    assert sm.correlation(a, a) == pytest.approx(1.0)


def test_copies_form_one_family_and_one_independent_bet() -> None:
    base = _noise(1)
    copies = [
        _series([r + 0.0001 * k * e for r, e in zip(base, _noise(10 + k), strict=True)])
        for k in range(4)
    ]
    corr = sm.matrix(copies)
    assert sm.families(corr) == [[0, 1, 2, 3]]
    assert sm.effective_count(corr) == pytest.approx(1.0, abs=0.01)


def test_independent_strategies_stay_apart_and_count_as_many() -> None:
    separate = [_series(_noise(k)) for k in range(5)]
    corr = sm.matrix(separate)
    assert sm.families(corr) == [[0], [1], [2], [3], [4]]
    assert sm.effective_count(corr) > 4.5


def test_two_momentum_twins_and_a_reversal_make_two_families() -> None:
    common = _noise(1)
    twin_a = _series([c + 0.3 * e for c, e in zip(common, _noise(2), strict=True)])
    twin_b = _series([c + 0.3 * e for c, e in zip(common, _noise(3), strict=True)])
    other = _series(_noise(4))
    assert sm.families(sm.matrix([twin_a, other, twin_b])) == [[0, 2], [1]]


def test_book_weights_families_equally_not_members() -> None:
    # Family one has three identical members returning 1%; family two one member returning 3%.
    one = dict.fromkeys(DAYS[:3], 0.01)
    two = dict.fromkeys(DAYS[:3], 0.03)
    out = sm.book([one, one, one, two], [[0, 1, 2], [3]])
    assert all(v == pytest.approx(0.02) for v in out.values())


def test_hedging_removes_the_market() -> None:
    market = _series(_noise(1))
    idio = _noise(2)
    strategy = {d: 1.2 * m + e for (d, m), e in zip(market.items(), idio, strict=True)}
    assert sm.beta(strategy, market) == pytest.approx(1.2, abs=0.05)
    left = sm.hedged(strategy, market)
    assert left is not None
    assert abs(sm.correlation(left, market) or 0.0) < 0.05


def test_build_is_deterministic_and_marks_the_book_as_not_a_candidate() -> None:
    market = _series(_noise(99))
    series = [
        sm.Series(
            f"s{k}", "c", _series([m + e for m, e in zip(market.values(), _noise(k), strict=True)])
        )
        for k in range(3)
    ]
    first = sm.build(series, market)
    second = sm.build(series, market)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["book"]["is_a_candidate"] is False
    # Sharing the market makes them alike; taking it out leaves them independent.
    assert first["average_correlation"] > 0.4
    assert abs(first["hedged"]["average_correlation"]) < 0.1
    assert first["hedged"]["effective_count"] > first["effective_count"]


def test_sharpe_is_annualised() -> None:
    rets = [0.001, -0.0005] * 200
    arr_mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - arr_mean) ** 2 for r in rets) / (len(rets) - 1))
    assert sm.sharpe(rets) == pytest.approx(arr_mean / sd * math.sqrt(252))


def test_nifty_returns_from_a_loader() -> None:
    closes = [(DAYS[0], 100.0), (DAYS[1], 110.0), (DAYS[2], 99.0)]
    got = sm.nifty_returns(lambda: closes)
    assert got == {DAYS[1]: pytest.approx(0.1), DAYS[2]: pytest.approx(-0.1)}


def test_main_writes_the_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sm, "nifty_returns", lambda loader=None: {})
    _write_report(tmp_path, "a", "c", _noise(1))
    _write_report(tmp_path, "b", "c", _noise(2))
    out = tmp_path / "map.json"
    assert sm.main(["--root", str(tmp_path), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert [s["strategy_id"] for s in result["strategies"]] == ["a", "b"]
    assert "hedged" not in result
