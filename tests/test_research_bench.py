"""The research bench (#163, #164, ADR-191): features an agent defines, IC and event studies,
and the agenda the loop reads and writes."""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest

from eulerlab.agents import lessons
from eulerlab.intraday import rule_engine as engine
from eulerlab.research import (
    agenda,
    agent_tools,
    combine,
    experiments,
    fast_eval,
    feature_registry,
    lang,
)
from test_research_autopilot import _data

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
END = date(2023, 12, 31)
STOCKS = 30
SESSIONS = 160


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    rules = Path(__file__).parents[1] / "config" / "constitution.yaml"
    (tmp_path / "config" / "constitution.yaml").write_text(rules.read_text())
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _panel(*, fade: bool = False) -> engine.Data:
    """Thirty random-walk stocks. With `fade`, one stock-session in ten gaps up 3% at the open
    and closes 2% under it: an event the study should find."""
    rng = random.Random(7)
    closes: dict[str, list[float]] = {}
    opens: dict[str, list[float]] = {}
    for k in range(STOCKS):
        c, o = [100.0], [100.0]
        for _ in range(1, SESSIONS):
            if fade and rng.random() < 0.1:
                o.append(c[-1] * 1.03)
                c.append(o[-1] * 0.98)
            else:
                o.append(c[-1] * (1 + rng.gauss(0, 0.005)))
                c.append(o[-1] * (1 + rng.gauss(0, 0.01)))
        closes[f"S{k:02d}"], opens[f"S{k:02d}"] = c, o
    return _data(closes, opens)


def _fast(data: engine.Data) -> fast_eval.FastEngine:
    return fast_eval.FastEngine(data, fast_eval.Store(engine.Engine(data)))


def _tools(data: engine.Data | None = None, **extra: int) -> agent_tools.ResearchTools:
    fast = _fast(data or _panel())
    return agent_tools.ResearchTools(
        asked_by="autopilot", discovery_end=END, now=NOW, engine=lambda end: fast, **extra
    )


def _define(tools: agent_tools.ResearchTools, name: str, formula: str) -> str:
    return tools.call("define_feature", json.dumps({"name": name, "formula": formula, "why": "w"}))


GAP_RATIO = "div(open_price, delay(close_price, 1))"


# --- features ------------------------------------------------------------------------------


def test_a_honest_feature_is_kept_and_usable_by_name(folder: Path) -> None:
    tools = _tools()
    assert "Kept gap_ratio" in _define(tools, "gap_ratio", GAP_RATIO)
    (row,) = feature_registry.rows()
    assert row["status"] == "kept" and row["author"] == "autopilot"
    assert row["checks"]["lookahead"] == "none found" and row["checks"]["coverage"] > 0.9
    assert feature_registry.expand("gt(gap_ratio, 1.02)") == f"gt({GAP_RATIO}, 1.02)"
    assert "gap_ratio" in tools.call("language", "{}")


def test_a_feature_reading_todays_close_is_refused_and_the_refusal_kept(folder: Path) -> None:
    out = _define(_tools(), "peek", "div(close_price, open_price)")
    assert "Refused" in out and "delay" in out
    (row,) = feature_registry.rows()
    assert row["status"] == "refused" and "delay" in row["refused_because"]
    assert feature_registry.kept() == {}


def test_measured_lookahead_catches_what_the_structure_check_cannot(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator that normalised over the whole time axis would pass the structural check."""

    def leaky(x: lang.Matrix) -> lang.Matrix:
        return np.asarray((x - np.nanmean(x)) / np.nanstd(x), dtype=np.float64)

    monkeypatch.setattr(lang, "_zscore", leaky)
    out = _define(_tools(), "leaky_z", "zscore(delay(day_return, 1))")
    assert "change when later ones are removed" in out


def test_a_copy_of_an_existing_field_is_refused(folder: Path) -> None:
    out = _define(_tools(), "double_day", "mul(delay(day_return, 1), 2)")
    assert "the same signal as day_return" in out


def test_a_name_taken_by_a_field_or_feature_is_refused(folder: Path) -> None:
    tools = _tools()
    assert "already a field" in _define(tools, "gap", GAP_RATIO)
    _define(tools, "gap_ratio", GAP_RATIO)
    assert "already a field" in _define(tools, "gap_ratio", "delay(day_return, 2)")


def test_a_kept_feature_screens_inside_a_formula_rule(folder: Path) -> None:
    tools = _tools()
    _define(tools, "gap_ratio", GAP_RATIO)
    spec = {"shape": "cross_section", "kind": "intraday", "score": "neg(gap_ratio)", "top": 5}
    out = tools.call("screen_formula", json.dumps({"spec": spec}))
    assert "net_sharpe" in out and "discovery only" in out
    (row,) = experiments.rows(purpose="screen")
    assert row["returns"] and row["metrics"]["explore"] is True


# --- measurements --------------------------------------------------------------------------


def test_feature_ic_reports_each_horizon_and_is_recorded(folder: Path) -> None:
    tools = _tools()
    out = tools.call(
        "feature_ic", json.dumps({"formula": "delay(day_return, 1)", "horizons": [1, 5]})
    )
    lines = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    assert [x["horizon"] for x in lines] == [1, 5]
    assert all(x["sessions"] > 100 for x in lines)
    (row,) = experiments.rows(purpose="screen")
    assert row["family"] == "ic:day_return" and row["returns"] is None
    assert len(tools.looks) == 1


def test_an_event_study_finds_a_planted_fade_and_beats_its_placebo(folder: Path) -> None:
    tools = _tools(_panel(fade=True))
    out = tools.call(
        "event_study", json.dumps({"formula": f"gt({GAP_RATIO}, 1.025)", "horizons": [1]})
    )
    (found,) = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    assert found["events"] > 300
    assert found["mean_bps"] < -100
    assert found["beats_placebo_share"] >= 0.95
    assert experiments.rows(purpose="screen")[0]["family"].startswith("event:")


def test_an_event_study_on_noise_does_not_beat_its_placebo(folder: Path) -> None:
    tools = _tools()
    out = tools.call(
        "event_study", json.dumps({"formula": "gt(delay(day_return, 1), 0.005)", "horizons": [1]})
    )
    (found,) = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    assert found["beats_placebo_share"] < 0.95


def test_looks_stop_at_the_runs_allowance(folder: Path) -> None:
    tools = _tools(max_looks=1)
    tools.call("feature_ic", json.dumps({"formula": "delay(day_return, 1)"}))
    assert "used its 1 looks" in tools.call("feature_ic", json.dumps({"formula": "gap"}))


def test_a_bad_formula_is_an_answer_not_a_crash(folder: Path) -> None:
    out = _tools().call("feature_ic", json.dumps({"formula": "close_price"}))
    assert "does not compile" in out
    assert experiments.rows(purpose="screen") == []


def test_forward_returns_start_at_the_entry_open() -> None:
    data = _data({"AAA": [100.0, 110.0, 121.0], "BBB": [100.0] * 3}, {"AAA": [100.0, 100.0, 110.0]})
    store = fast_eval.Store(engine.Engine(data))
    one = combine.forward_returns(store, 1)
    two = combine.forward_returns(store, 2)
    # AAA: open 100 -> close 110 on session 1 is +10%, BBB flat; net of the mean, +5%.
    assert one[1, 0] == pytest.approx(0.05)
    assert two[1, 0] == pytest.approx((121 / 100 - 1) / 2)
    assert np.isnan(two[2]).all()  # no session after the last


# --- the agenda ----------------------------------------------------------------------------


def test_the_same_question_is_asked_once(folder: Path) -> None:
    a = agenda.ask("Do large gap-ups fade by the close?", "overreaction", author="autopilot")
    b = agenda.ask("do large  gap-ups fade by the close?", "again", author="operator")
    assert a == b and len(agenda.questions()) == 1


def test_findings_status_and_next_step_fold_into_the_question(folder: Path) -> None:
    qid = agenda.ask("Does delivery share predict swing returns?", "informed buyers", author="op")
    agenda.note(qid, "IC 0.01 at 5 sessions", author="autopilot", refs=["abc"], next_step="sector")
    q = agenda.note(qid, "dead after neutralising", author="autopilot", status="dead")
    assert q.status == "dead" and q.next == "sector" and len(q.findings) == 2
    assert q.findings[0]["refs"] == ["abc"]
    assert agenda.ranked() == []


def test_the_least_explored_question_comes_first(folder: Path) -> None:
    old = agenda.ask("First question asked here?", "w", author="op", now=NOW)
    new = agenda.ask("Second question asked here?", "w", author="op", now=NOW)
    agenda.note(old, "one finding", author="autopilot", now=NOW)
    assert [q.id for q in agenda.ranked()] == [new, old]
    text = agenda.summary(limit=1)
    assert new in text and old not in text and "1 more open" in text


def test_the_loop_writes_findings_with_its_looks_as_refs(folder: Path) -> None:
    tools = _tools()
    out = tools.call(
        "ask_question", json.dumps({"question": "Is yesterday's move reversed?", "why": "w"})
    )
    qid = out.split()[-1].rstrip(".")
    tools.call("feature_ic", json.dumps({"formula": "delay(day_return, 1)"}))
    tools.call("record_finding", json.dumps({"id": qid, "finding": "no", "status": "answered"}))
    q = agenda.questions()[qid]
    assert q.status == "answered" and q.findings[0]["refs"] == [tools.looks[0]["id"]]
    assert tools.questions == {qid}


def test_the_operator_adds_and_closes_from_the_command_line(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agenda.main(["--ask", "Do index rebalances move stocks?", "--why", "forced flows"])
    qid = capsys.readouterr().out.strip()
    agenda.main(["--close", qid, "--status", "dead", "--note", "no data"])
    assert agenda.questions()[qid].status == "dead"
    assert agenda.questions()[qid].findings[0]["by"] == "operator"


def test_an_empty_agenda_says_how_to_start(folder: Path) -> None:
    assert "ask_question" in agenda.summary()


# --- lessons apply to formula rules --------------------------------------------------------


def test_a_price_only_formula_rule_breaks_the_price_lesson() -> None:
    spec = lang.Spec(
        shape="event", kind="intraday", side="short", when="gt(gap, 0.02)", score="gap"
    )
    assert lessons.CHECKS["price_only_intraday"](spec)
    assert lessons.CHECKS["results_short_after_drop"](spec) == ""
    other = lang.Spec(
        shape="event", kind="intraday", when="and(gt(gap, 0.02), results_morning)", score="gap"
    )
    assert lessons.CHECKS["price_only_intraday"](other) == ""


# --- combining weak signals (#155) ---------------------------------------------------------


def _planted(n: int = 420, stocks: int = 40, seed: int = 11) -> engine.Data:
    """Each session's open-to-close move fades its own gap and the day before's move, a little."""
    rng = random.Random(seed)
    closes: dict[str, list[float]] = {}
    opens: dict[str, list[float]] = {}
    for k in range(stocks):
        c, o, last = [100.0], [100.0], 0.0
        for _ in range(1, n):
            gap = rng.gauss(0, 0.01)
            o.append(c[-1] * (1 + gap))
            move = -0.25 * gap - 0.15 * last + rng.gauss(0, 0.01)
            c.append(o[-1] * (1 + move))
            last = move
        closes[f"S{k:02d}"], opens[f"S{k:02d}"] = c, o
    return _data(closes, opens)


WEAK = ["neg(gap)", "neg(delay(day_return, 1))"]


def test_the_combined_book_finds_two_planted_weak_signals() -> None:
    found = combine.combine(_fast(_planted()), WEAK, kind="intraday")
    screen = found["screen"]
    assert screen["count"] > 100 and screen["net"]["sharpe"] > 1
    weights = found["months"][-1]["weights"]
    assert all(w > 0 for w in weights.values()) and len(weights) == 2
    assert found["rule"].first > _planted().sessions[combine.MIN_TRAIN - 1]
    assert found["cost_share"] is not None and 0 < found["cost_share"] < 1
    assert set(found["ic_decay"]["neg(gap)"]) == set(combine.DECAY_HORIZONS)


def test_the_walk_forward_forecast_never_reads_the_future() -> None:
    data = _planted()
    trees = [lang.compile_text(f) for f in WEAK]
    before = combine.walk_forward(_fast(data).store, trees, horizon=1).values
    cut = 330
    for bars in data.panel.values():
        for d in data.sessions[cut:]:
            bars[d] = type(bars[d])(bars[d].open, bars[d].close * 1.5, bars[d].value)
    after = combine.walk_forward(_fast(data).store, trees, horizon=1).values
    assert np.array_equal(before[:cut], after[:cut], equal_nan=True)
    assert not np.array_equal(before[cut + 30 :], after[cut + 30 :], equal_nan=True)


def test_nothing_is_traded_inside_the_cost_band() -> None:
    fast = _fast(_planted())
    trees = [lang.compile_text(f) for f in WEAK]
    fit = combine.walk_forward(fast.store, trees, horizon=1)
    assert combine.entries(fit, fast.store, "intraday", band=lambda d: 1.0) == []
    swing = combine.entries(fit, fast.store, "swing", band=lambda d: 0.0)
    assert swing and all(side == 1 for _, _, side, _ in swing)


def test_the_band_is_the_round_trips_own_cost() -> None:
    intraday = combine.cost_band("intraday", date(2023, 3, 1))
    swing = combine.cost_band("swing", date(2023, 3, 1))
    assert 0.0008 < intraday < 0.002 < swing < 0.005  # about 12 bps and 26 bps


def test_ridge_fits_and_a_bad_book_is_refused() -> None:
    fast = _fast(_planted())
    found = combine.combine(fast, WEAK, kind="swing", hold=3, method="ridge")
    assert found["rule"].method == "ridge" and found["months"]
    with pytest.raises(ValueError, match="2 to"):
        combine.combine(fast, ["gap"], kind="intraday")
    with pytest.raises(ValueError, match="hold must be 0"):
        combine.combine(fast, WEAK, kind="intraday", hold=3)


def test_the_agent_combines_signals_as_one_recorded_screen(folder: Path) -> None:
    tools = _tools(_planted())
    out = tools.call("combine_signals", json.dumps({"formulas": WEAK, "kind": "intraday"}))
    assert "out of sample from" in out and "cost_share" in out
    (row,) = experiments.rows(purpose="screen")
    assert row["family"] == "combined:intraday:day_return+gap" and row["returns"]
    assert len(tools.screened) == 1
    again = tools.call("combine_signals", json.dumps({"formulas": WEAK, "kind": "intraday"}))
    assert "Already screened" in again
