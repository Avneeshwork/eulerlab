"""Strategy language v2 and the fast evaluator (ADR-175): same entries as the engine, no look-ahead."""

from __future__ import annotations

import itertools
import os
import random
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from eulerlab.agents.workers import autopilot as writer
from eulerlab.features.formula import FormulaError
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import rule_engine as engine
from eulerlab.research import fast_eval, lang
from test_research_autopilot import GAP_FADE, _data, _sessions


def _market(n: int = 160, stocks: int = 12, seed: int = 7) -> engine.Data:
    rng = random.Random(seed)
    closes: dict[str, list[float]] = {}
    opens: dict[str, list[float]] = {}
    for k in range(stocks):
        price, cs, os_ = 100.0 + k, [], []
        for _ in range(n):
            open_ = price * (1 + rng.gauss(0, 0.02))
            price = open_ * (1 + rng.gauss(0, 0.02))
            os_.append(round(open_, 2))
            cs.append(round(price, 2))
        closes[f"S{k:02d}"], opens[f"S{k:02d}"] = cs, os_
    days = _sessions(n)
    delivery = {s: {d: rng.uniform(0.2, 3.0) for d in days} for s in closes}
    buys = {s: dict.fromkeys(rng.sample(days, 12), 1.0) for s in list(closes)[:6]}
    return _data(closes, opens, delivery=delivery, buys=buys)


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> fast_eval.FastEngine:
    monkeypatch.setattr(engine.Engine, "short", frozenset())
    data = _market()
    data.__dict__["mornings"] = frozenset()
    slow = engine.Engine(data)
    sectors = {s: ("bank" if i % 2 else "auto") for i, s in enumerate(sorted(data.panel))}
    return fast_eval.FastEngine(data, fast_eval.Store(slow, sectors=sectors))


def test_every_reference_rule_and_200_random_ones_make_the_engines_entries(
    fast: fast_eval.FastEngine,
) -> None:
    slow = engine.Engine(fast.data)
    specs = [s for s in engine.reference_specs().values() if "promoter_buy" not in s.describe()]
    specs.append(engine.RuleSpec.model_validate(GAP_FADE))
    known: dict[str, str] = {}
    for seed in range(4):
        for card in writer.fallback(50, seed, known):
            specs.append(card["spec"])
            known[card["spec"].fingerprint()] = "x"
    assert len(specs) > 150
    fired = 0
    for spec in specs:
        want = slow.events(spec)
        assert fast.events(spec) == want, spec.describe()
        fired += bool(want)
    assert fired > 50, "the comparison must not be of empty lists"


def test_a_screen_through_the_tables_is_the_engines_screen(fast: fast_eval.FastEngine) -> None:
    spec = engine.RuleSpec.model_validate(
        {**GAP_FADE, "when": [{"signal": "gap", "op": ">=", "value": 0.01, "absolute": True}]}
    )
    assert fast.screen(spec) == engine.Engine(fast.data).screen(spec)


def test_reading_a_close_on_the_entry_day_does_not_compile() -> None:
    with pytest.raises(lang.LookAhead, match="delay"):
        lang.compile_text("rank(ret(5))")
    with pytest.raises(lang.LookAhead):
        lang.compile_text("ts_mean(delivery_ratio, 20)")
    with pytest.raises(lang.LookAhead):
        lang.compile_text("mul(gap, fii_net)")
    lang.compile_text("mul(gap, delay(fii_net, 1))")
    lang.compile_text("rank(delay(ret(5), 1))")
    with pytest.raises(ValidationError):
        lang.Spec(shape="cross_section", kind="swing", hold=5, score="ret(5)")


def test_unknown_names_and_oversize_trees_are_refused() -> None:
    with pytest.raises(FormulaError, match="unknown operator"):
        lang.compile_text("exec(gap)")
    with pytest.raises(FormulaError):
        lang.compile_text("delay(gap, 999)")


def test_a_sector_neutral_factor_runs_end_to_end(fast: fast_eval.FastEngine) -> None:
    spec = lang.Spec(
        shape="cross_section",
        kind="swing",
        hold=5,
        score="neutralize(rank(neg(delay(ret(5), 1))))",
        top=3,
        every=5,
        first=fast.data.sessions[10],
    )
    events = fast.events(spec)
    by_day: dict[date, list[str]] = {}
    for day, symbol, side, _ in events:
        assert side == 1
        by_day.setdefault(day, []).append(symbol)
    assert by_day and all(len(v) <= 3 for v in by_day.values())
    days = sorted(by_day)
    index = fast.data.index
    assert all(index[b] - index[a] >= 5 for a, b in itertools.pairwise(days))
    # The names picked are the top three by the score known that morning.
    score = fast.evaluator.value(spec.trees["score"])
    t = fast.store.days.index(days[0])
    best = np.argsort(-np.nan_to_num(score[t], nan=-9.0), kind="stable")[:3]
    assert sorted(fast.store.symbols[j] for j in best) == sorted(by_day[days[0]])
    found = fast.screen(spec)
    assert found["count"] > 0 and found["kind"] == "swing"
    assert spec.complexity["fields"] == ["ret"] and spec.complexity["size"] == 6


def test_neutralize_takes_out_the_sector_mean(fast: fast_eval.FastEngine) -> None:
    out = fast.evaluator.value(lang.compile_text("neutralize(delay(ret(1), 1))"))
    groups = fast.store.groups()
    for g in (0, 1):
        assert np.allclose(np.nanmean(out[5:, groups == g], axis=1), 0.0, atol=1e-12)


def test_market_wide_fields_are_signals_on_every_stock(fast: fast_eval.FastEngine) -> None:
    day = fast.data.sessions[20]
    store = fast_eval.Store(engine.Engine(fast.data), market={"fii_net": {day: -500.0}})
    ev = lang.Evaluator(store)
    table = ev.value(lang.compile_text("lt(delay(fii_net, 1), 0)"))
    assert table[21].all() and not table[20].any()


def test_tables_round_trip_through_parquet_with_both_times(
    fast: fast_eval.FastEngine, tmp_path: Path
) -> None:
    import pyarrow.parquet as pq

    first = fast_eval.Store(engine.Engine(fast.data), cache=tmp_path)
    built = first.field("ret", 5)
    again = fast_eval.Store(engine.Engine(fast.data), cache=tmp_path)
    assert np.array_equal(again.field("ret", 5), built, equal_nan=True)
    (path,) = (tmp_path / first.version).glob("*.parquet")
    assert {"event_time", "knowledge_time", "session", "symbol", "value"} == set(
        pq.read_table(path).column_names
    )


def test_evaluate_records_each_candidate(
    fast: fast_eval.FastEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.research import experiments

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    rules = Path(__file__).parents[1] / "config" / "constitution.yaml"
    (tmp_path / "config" / "constitution.yaml").write_text(rules.read_text())
    monkeypatch.setattr(experiments, "PATH", tmp_path / "e.jsonl")
    monkeypatch.setattr(experiments, "RETURNS", tmp_path / "r")
    spec = engine.RuleSpec.model_validate(GAP_FADE)
    (found,) = fast_eval.evaluate([spec], fast, asked_by="test", family="gap")
    (row,) = experiments.rows()
    assert row["id"] == found["id"] and row["purpose"] == "sweep" and row["family"] == "gap"


def _day(closes: list[float]) -> ip.Day:
    n = len(closes)
    return ip.Day(
        date(2025, 3, 3), tuple(closes), tuple(closes), tuple(closes), tuple(closes),
        tuple([1000.0] * n), n - 1,
    )  # fmt: skip


def test_a_minute_rule_fills_on_the_bar_after_the_one_that_fired() -> None:
    closes = [100.0] * 40 + [103.0] * 335
    spec = lang.MinuteSpec(entry="gt(close, mul(ts_mean(close, 20), 1.01))", side="long")
    trade = lang.minute_trade(spec, "AAA", _day(closes))
    assert trade is not None
    assert (trade.entry_minute, trade.exit_minute, trade.direction) == (41, 355, 1)
    assert trade.costs > 0
    assert lang.minute_trade(spec, "AAA", _day([100.0] * 375)) is None
    with pytest.raises(ValidationError):
        lang.MinuteSpec(entry="rank(close)", side="long")


@pytest.mark.skipif(not os.environ.get("RULE_ENGINE_REPRO"), reason="needs the panel")
def test_the_tables_reproduce_research_176_on_real_data() -> None:
    """Issue #140: the ten reference rules come out exactly through the batch path."""
    data = engine.Data()
    slow, quick = engine.Engine(data), fast_eval.FastEngine(data)
    for h, spec in engine.reference_specs().items():
        assert quick.screen(spec) == slow.screen(spec), h


def test_a_card_with_a_v2_rule_runs_on_the_plain_engine(
    fast: fast_eval.FastEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate and the paper books build a plain `Engine`: a v2 card must work there too."""
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    body = {"shape": "cross_section", "kind": "swing", "hold": 5, "top": 3, "every": 5}
    spec = lang.Spec(**body, score="rank(neg(delay(ret(5), 1)))", first=fast.data.sessions[10])
    (tmp_path / "H-9001.yaml").write_text(
        "id: H-9001\nengine_v2: " + spec.model_dump_json(exclude_defaults=True) + "\n"
    )
    read = engine.card_spec("H-9001", tmp_path)
    assert isinstance(read, lang.Spec) and read.fingerprint() == spec.fingerprint()
    plain = engine.Engine(fast.data)
    assert plain.events(read) == fast.events(spec) != []
    assert plain.screen(read)["count"] > 0
