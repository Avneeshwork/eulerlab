"""The forward shadow (#156, ADR-189): every screened rule scored on the forward period,
and the haircut it measures. Also HISTORY #91: swings past the research window."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.intraday import rule_engine as engine
from eulerlab.research import experiments, fast_eval, forward_shadow, lang
from test_research_autopilot import GAP_FADE, _data, _sessions

NOW = datetime(2026, 11, 14, 18, tzinfo=UTC)
START = date(2026, 1, 1)


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    rules = Path(__file__).parents[1] / "config" / "constitution.yaml"
    (tmp_path / "config" / "constitution.yaml").write_text(rules.read_text())
    (tmp_path / "hypotheses").mkdir()
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _live(n: int = 120) -> engine.Data:
    """Two stocks over late 2025 and 2026, AAA gapping up every third session."""
    closes = {s: [100.0] * n for s in ("AAA", "BBB")}
    opens = {s: [100.0] * n for s in ("AAA", "BBB")}
    for i in range(5, n - 5, 3):
        opens["AAA"][i] = 104.0
    data = _data(closes, opens)
    days = _sessions(n, date(2025, 10, 1))
    moved = dict(zip(data.sessions, days, strict=True))
    data.panel = {s: {moved[d]: bar for d, bar in bars.items()} for s, bars in data.panel.items()}
    data.sessions = days
    data.index = {d: i for i, d in enumerate(days)}
    data.liquid = {d: frozenset(closes) for d in days}
    data.t2t = {d: frozenset() for d in days}
    data.end = days[-1]
    return data


SWING = {**GAP_FADE, "kind": "swing", "hold": 3, "side": "with"}


def test_swings_after_the_research_window_are_kept() -> None:
    """HISTORY #91: the swing book cut exits at 2024-11-30 whatever the data's own end."""
    spec = engine.RuleSpec.model_validate(SWING)
    found = engine.Engine(_live()).swings(spec)
    assert found and min(s.entry_day for s in found) > date(2025, 1, 1)


def _record(spec: Any, sharpe: float, *, with_spec: bool = True, hypothesis: str = "") -> None:
    experiments.record(
        purpose="screen",
        fingerprint=spec.fingerprint(),
        first=date(2016, 1, 1),
        end=date(2023, 12, 31),
        metrics={"net_sharpe": sharpe},
        hypothesis=hypothesis,
        family="intraday:gap",
        asked_by="autopilot",
        now=datetime(2026, 2, 1, tzinfo=UTC),
        spec=spec.model_dump(mode="json") if with_spec else None,
    )


def test_the_population_is_rebuilt_from_each_rows_own_spec(folder: Path) -> None:
    rule = engine.RuleSpec.model_validate(GAP_FADE)
    formula = lang.Spec(shape="event", kind="intraday", when="gt(gap, 0.02)", score="gap")
    lost = engine.RuleSpec.model_validate(SWING)
    _record(rule, 1.5)
    _record(formula, 0.4)
    _record(lost, 2.0, with_spec=False)  # no spec, no card: cannot be rebuilt
    found = {c.fingerprint: c for c in forward_shadow.population()}
    assert set(found) == {rule.fingerprint(), formula.fingerprint()}
    assert found[rule.fingerprint()].backtest_sharpe == 1.5
    assert found[rule.fingerprint()].recorded == date(2026, 2, 1)


def test_a_rule_is_scored_only_on_the_forward_period(folder: Path) -> None:
    data = _live()
    rule = engine.RuleSpec.model_validate(GAP_FADE)
    _record(rule, 1.5)
    shadow = forward_shadow.forward_engine(data, START, fast_eval.Store(engine.Engine(data)))
    out = forward_shadow.run(engine=shadow, now=NOW)
    assert out == {"rules": 1, "errors": 0, "forward_start": "2026-01-01"}
    (row,) = forward_shadow.latest()
    assert row["forward_sessions"] == sum(1 for d in data.sessions if d >= START)
    assert row["trades"] > 0 and row["kind"] == "intraday"
    assert row["since_recorded"]["sessions"] < row["forward_sessions"]
    assert row["backtest_sharpe"] == 1.5


def test_the_sample_puts_cards_first_and_is_stable(folder: Path) -> None:
    rule = engine.RuleSpec.model_validate(GAP_FADE)

    def candidate(fp: str, h: str = "") -> forward_shadow.Candidate:
        return forward_shadow.Candidate(fp, rule, h, "s", "f", 1.0, date(2026, 1, 1))

    pool = [candidate(f"f{i}") for i in range(10)] + [candidate("card", "H-0001")]
    first = forward_shadow.sample(pool, 4)
    assert first[0].hypothesis == "H-0001"
    assert [c.fingerprint for c in forward_shadow.sample(list(reversed(pool)), 4)] == [
        c.fingerprint for c in first
    ]


def _rows(n: int, slope: float, seed: int = 3) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        bt = rng.uniform(-1, 3)
        out.append(
            {
                "fingerprint": f"r{i}",
                "backtest_sharpe": bt,
                "forward_sharpe": slope * bt + rng.gauss(0, 0.3),
                "forward_sessions": 80,
                "source": "autopilot" if i % 2 else "evolve",
                "family": "intraday:gap",
                "kind": "swing" if i % 3 else "intraday",
                "hold": 5,
            }
        )
    return out


def test_the_haircut_is_the_slope_with_an_interval() -> None:
    found = forward_shadow.haircut(_rows(250, 0.5))
    assert found["enough"] and found["rules"] == 250
    assert found["slope_ci"][0] < 0.5 < found["slope_ci"][1]
    assert found["rank_correlation"] > 0.5
    assert forward_shadow.expected_live(2.0, found) == pytest.approx(
        found["intercept"] + 2 * found["slope"], abs=1e-3
    )


def test_a_short_record_is_not_enough_and_predicts_nothing() -> None:
    rows = _rows(250, 0.5)
    for r in rows:
        r["forward_sessions"] = 20
    found = forward_shadow.haircut(rows)
    assert found["rules"] == 0 and not found["enough"]
    assert forward_shadow.expected_live(2.0, forward_shadow.haircut(_rows(50, 0.5))) is None


def test_the_report_breaks_down_by_source_hold_and_score(folder: Path) -> None:
    rows = _rows(250, 0.5)
    by_source = forward_shadow.breakdown(rows, "source")
    assert {r["source"] for r in by_source} == {"autopilot", "evolve"}
    by_score = forward_shadow.breakdown(rows, "score")
    assert len(by_score) == 5 and by_score[0]["forward"] < by_score[-1]["forward"]
    text = forward_shadow.markdown(rows)
    assert "Haircut" in text and "## By hold" in text and "swing 2-5" in text
