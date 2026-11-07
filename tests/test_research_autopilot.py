"""The research autopilot (ADR-150): the rule engine, the card writer and the loop.

Synthetic sessions, so each rule's events and each step of the loop are pinned
without market data. The engine's match with research 176's published numbers
needs the real panel and takes about three minutes: `make rule-engine-check`
(or RULE_ENGINE_REPRO=1 for the test at the bottom).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from eulerlab.agents.workers import autopilot as writer
from eulerlab.intraday import daily_universe_screen as du
from eulerlab.intraday import rule_engine as engine

# --- synthetic data ---------------------------------------------------------------------


def _sessions(n: int, start: date = date(2022, 1, 3)) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _data(
    closes: dict[str, list[float]],
    opens: dict[str, list[float]] | None = None,
    *,
    delivery: dict[str, dict[date, float]] | None = None,
    buys: dict[str, dict[date, float]] | None = None,
) -> engine.Data:
    n = len(next(iter(closes.values())))
    sessions = _sessions(n)
    data = object.__new__(engine.Data)
    data.panel = {
        s: {d: du.Bar((opens or {}).get(s, c)[i], c[i], 1e9) for i, d in enumerate(sessions)}
        for s, c in closes.items()
    }
    data.sessions = sessions
    data.index = {d: i for i, d in enumerate(sessions)}
    data.liquid = {d: frozenset(closes) for d in sessions}
    data.delivery = delivery or {}
    data.t2t = {d: frozenset() for d in sessions}
    data.buys, data.sells = buys or {}, {}
    data.results = {}
    data.__dict__["promoters"] = {}
    return data


GAP_FADE = {
    "kind": "intraday",
    "side": "against",
    "direction_of": {"signal": "gap"},
    "when": [{"signal": "gap", "op": ">=", "value": 0.03, "absolute": True}],
    "rank_by": {"signal": "gap", "absolute": True, "order": "desc"},
}


# --- the spec ---------------------------------------------------------------------------


def test_a_close_read_on_the_entry_day_does_not_parse() -> None:
    with pytest.raises(ValidationError, match="lag must be >= 1"):
        engine.RuleSpec.model_validate(
            {**GAP_FADE, "when": [{"signal": "ret", "lag": 0, "op": ">", "value": 0}]}
        )


def test_swing_rules_are_long_only_and_hold_two_or_more_sessions() -> None:
    with pytest.raises(ValidationError, match="long only"):
        engine.RuleSpec.model_validate({**GAP_FADE, "kind": "swing", "hold": 5, "side": "short"})
    with pytest.raises(ValidationError, match="2 to 60"):
        engine.RuleSpec.model_validate({**GAP_FADE, "kind": "swing", "hold": 0})


def test_against_needs_a_direction() -> None:
    body = {k: v for k, v in GAP_FADE.items() if k != "direction_of"}
    with pytest.raises(ValidationError, match="direction_of"):
        engine.RuleSpec.model_validate(body)


def test_the_window_is_the_datas_not_the_cards() -> None:
    assert engine.RuleSpec.model_validate(GAP_FADE).first == engine.FIRST
    bulk = engine.reference_specs()["H-0166"]
    assert bulk.first == engine.REPORTS_FIRST


def test_fingerprint_ignores_condition_order() -> None:
    a = engine.reference_specs()["H-0164"]
    body = a.model_dump(mode="json")
    body["when"] = list(reversed(body["when"]))
    assert engine.RuleSpec.model_validate(body).fingerprint() == a.fingerprint()
    assert len({s.fingerprint() for s in engine.reference_specs().values()}) == 10


# --- the engine -------------------------------------------------------------------------


def test_gap_fade_trades_against_the_gap_at_the_open() -> None:
    closes = {"AAA": [100.0] * 30, "BBB": [100.0] * 30}
    opens = {"AAA": [100.0] * 30, "BBB": [100.0] * 30}
    opens["AAA"][25] = 104.0  # gap up 4%: short
    opens["BBB"][26] = 95.0  # gap down 5%: long
    data = _data(closes, opens)
    events = engine.Engine(data).events(engine.RuleSpec.model_validate(GAP_FADE))
    assert [(d, s, side) for d, s, side, _ in events] == [
        (data.sessions[25], "AAA", -1),
        (data.sessions[26], "BBB", 1),
    ]


def test_a_swing_rule_drops_the_short_side() -> None:
    closes = {"AAA": [100.0] * 30}
    opens = {"AAA": [100.0] * 30}
    opens["AAA"][25] = 104.0
    data = _data(closes, opens)
    spec = engine.RuleSpec.model_validate({**GAP_FADE, "kind": "swing", "hold": 3})
    assert engine.Engine(data).events(spec) == []


def test_at_high_matches_a_plain_scan() -> None:
    closes = {"AAA": [100 + (i % 7) * (1 if i % 11 else -3) for i in range(60)]}
    data = _data({"AAA": [float(c) for c in closes["AAA"]]})
    n = 10
    hits = data.extremes(n, high=True)["AAA"]
    c = data.panel["AAA"]
    days = data.sessions
    plain = {
        days[k]
        for k in range(n, len(days))
        if c[days[k]].close >= max(c[d].close for d in days[k - n : k])
    }
    assert hits == plain


def test_lag_reads_the_session_before_entry() -> None:
    closes = {"AAA": [100.0] * 30}
    closes["AAA"][20] = 104.0  # +4% close-to-close on session 20
    data = _data(closes)
    spec = engine.RuleSpec.model_validate(
        {
            "kind": "intraday",
            "side": "long",
            "when": [{"signal": "ret", "lag": 1, "op": ">=", "value": 0.03}],
            "rank_by": {"signal": "ret", "lag": 1},
        }
    )
    assert [e[0] for e in engine.Engine(data).events(spec)] == [data.sessions[21]]


def test_a_rule_that_never_fires_is_flagged() -> None:
    data = _data({"AAA": [100.0] * 40})
    out = engine.Engine(data).screen(engine.RuleSpec.model_validate(GAP_FADE))
    assert out["count"] == 0
    assert not out["clean"]
    assert any(c["check"] == "enough trades" and c["flag"] for c in out["checks"])


# --- the card writer --------------------------------------------------------------------


def test_parse_reads_a_fenced_answer_and_ignores_prose() -> None:
    answer = 'Here:\n```json\n{"cards": [{"title": "x", "engine": {}}]}\n```'
    assert writer.parse(answer) == [{"title": "x", "engine": {}}]
    assert writer.parse("no json") == []


def test_accept_drops_invalid_specs_and_repeats() -> None:
    known = {engine.reference_specs()["H-0168"].fingerprint(): "H-0168"}
    raw = [
        {"title": "the H-0168 again", "engine": engine.REFERENCE["H-0168"]},
        {
            "title": "lookahead",
            "engine": {**GAP_FADE, "when": [{"signal": "ret", "op": ">", "value": 0}]},
        },
        {
            "title": "new",
            "engine": {
                **GAP_FADE,
                "when": [{"signal": "gap", "op": ">=", "value": 0.05, "absolute": True}],
            },
        },
    ]
    kept, dropped = writer.accept(raw, known)
    assert [c["title"] for c in kept] == ["new"]
    assert any("repeats H-0168" in d for d in dropped)
    assert any("lookahead" in d for d in dropped)


def test_fallback_writes_new_rules_half_intraday_half_swing() -> None:
    known = engine.known_fingerprints(Path("/nonexistent"))
    out = writer.fallback(6, 7, known)
    assert len(out) == 6
    kinds = [c["spec"].kind for c in out]
    assert kinds.count("intraday") == 3 and kinds.count("swing") == 3
    assert len({c["spec"].fingerprint() for c in out}) == 6
    assert not {c["spec"].fingerprint() for c in out} & set(known)


def test_a_written_card_reads_back_as_the_same_rule(tmp_path: Path) -> None:
    spec = engine.RuleSpec.model_validate(GAP_FADE)
    text = writer.card_yaml(
        "H-0999",
        {"title": "t", "claim": "c", "spec": spec},
        day=date(2026, 11, 7),
        model="claude-sonnet",
        tried_count=173,
    )
    (tmp_path / "H-0999.yaml").write_text(text)
    raw = yaml.safe_load(text)
    assert raw["holdout"] == {"starts": "2024-12-01", "status": "unread"}
    assert engine.card_spec("H-0999", tmp_path) == spec
    from eulerlab.validation import holdout

    assert holdout.load(tmp_path / "H-0999.yaml").id == "H-0999"


def test_next_ids_follow_the_highest_card(tmp_path: Path) -> None:
    (tmp_path / "H-0173.yaml").write_text("id: H-0173\n")
    assert writer.next_ids(2, tmp_path) == ["H-0174", "H-0175"]


# --- the loop ---------------------------------------------------------------------------


class _Ctx:
    """Enough of `runtime.Context` for the loop."""

    def __init__(self, root: Path, answer: str, options: dict[str, Any] | None = None) -> None:
        self.root = root
        self.out_dir = root / "autopilot" / "run"
        self.now = datetime(2026, 11, 7, 12, tzinfo=UTC)
        self.options = {"cards": 2, **(options or {})}
        self.notes: list[str] = []
        self.steps: list[str] = []
        self.model = "claude-sonnet"
        self.requests = 0
        self._answer = answer

    def can_ask(self) -> bool:
        return True

    def ask(self, system: str, user: str, accept: Any = None) -> str:
        self.requests += 1
        return self._answer

    def step(self, text: str, kind: str = "step") -> None:
        self.steps.append(text)


def _answer() -> str:
    swing = {**GAP_FADE, "kind": "swing", "hold": 3, "side": "with"}
    intraday = {
        **GAP_FADE,
        "when": [{"signal": "gap", "op": ">=", "value": 0.03, "absolute": True}],
    }
    return json.dumps(
        {
            "cards": [
                {"title": "gap fade", "claim": "c", "rationale": "r", "engine": intraday},
                {"title": "gap follow", "claim": "c", "rationale": "r", "engine": swing},
            ]
        }
    )


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "docs" / "RESEARCH").mkdir(parents=True)
    (tmp_path / "research" / "papers").mkdir(parents=True)
    (tmp_path / "hypotheses" / "H-0173.yaml").write_text("id: H-0173\ntitle: old\n")
    return tmp_path


def _gappy() -> engine.Data:
    closes = {s: [100.0] * 80 for s in ("AAA", "BBB")}
    opens = {s: [100.0] * 80 for s in ("AAA", "BBB")}
    for i in range(5, 75, 3):
        opens["AAA"][i] = 104.0
    return _data(closes, opens)


def test_cards_are_committed_before_anything_is_screened(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.research import autopilot

    calls: list[list[str]] = []

    def fake_git(args: Any) -> tuple[int, str]:
        calls.append(list(args))
        return 0, ""

    screened: list[str] = []
    real = engine.Engine.screen

    def spy(self: engine.Engine, spec: engine.RuleSpec) -> dict[str, Any]:
        screened.append(spec.fingerprint())
        assert any(c[0] == "commit" for c in calls), "screened before the commit"
        return real(self, spec)

    monkeypatch.setattr(engine.Engine, "screen", spy)
    monkeypatch.setattr("eulerlab.agents.runtime.outputs", lambda *a, **k: [])
    ctx = _Ctx(folder / "agents", _answer())
    result = autopilot.pipeline(ctx, run_git=fake_git, data=_gappy())  # type: ignore[arg-type]
    assert len(screened) == 2
    first_commit = next(c for c in calls if c[0] == "commit")
    assert "--only" in first_commit and "hypotheses/H-0174.yaml" in first_commit
    assert result.data["cards"][0]["id"] == "H-0174"
    raw = yaml.safe_load((folder / "hypotheses" / "H-0174.yaml").read_text())
    assert raw["result"].startswith("Autopilot screen 2026-11-07")
    assert list((folder / "docs" / "RESEARCH").glob("001-autopilot-2026-11-07.md"))


def test_a_failed_commit_stops_the_run_before_the_screen(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.research import autopilot

    def broken_git(args: Any) -> tuple[int, str]:
        return (1, "hook failed") if args[0] == "commit" else (0, "")

    def never(self: engine.Engine, spec: engine.RuleSpec) -> dict[str, Any]:
        raise AssertionError("screened without a pre-registration")

    monkeypatch.setattr(engine.Engine, "screen", never)
    ctx = _Ctx(folder / "agents", _answer())
    result = autopilot.pipeline(ctx, run_git=broken_git, data=_gappy())  # type: ignore[arg-type]
    assert result.status == "failed"
    assert "nothing screened" in result.summary


def test_the_gate_stops_at_the_weeks_allowance(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.research import autopilot

    clean = {"clean": True, "passes_screen": True}

    def fake_screen(self: engine.Engine, spec: engine.RuleSpec) -> dict[str, Any]:
        return {
            **clean,
            "kind": spec.kind,
            "rule": spec.describe(),
            "count": 500,
            "first": "2016-01-01",
            "per_bps": {"net_mean": 10.0},
            "net": {"sharpe": 1.0},
            "halves": {"first": {"sharpe": 1.0}, "second": {"sharpe": 1.0}},
            "net_at_2x_costs": {"sharpe": 0.5},
            "checks": [],
        }

    gated: list[str] = []

    def fake_gate(h: str, out_dir: Path) -> dict[str, Any]:
        gated.append(h)
        return {"hypothesis": h, "verdict": "KILL", "entries": 2}

    monkeypatch.setattr(engine.Engine, "screen", fake_screen)
    monkeypatch.setattr(autopilot, "gate_one", fake_gate)
    monkeypatch.setattr("eulerlab.agents.runtime.outputs", lambda *a, **k: [])
    ctx = _Ctx(folder / "agents", _answer(), {"gate_entries_per_week": 2})
    result = autopilot.pipeline(ctx, run_git=lambda a: (0, ""), data=_gappy())  # type: ignore[arg-type]
    assert gated == ["H-0174"]
    assert result.data["survivors"] == ["H-0174", "H-0175"]
    assert any("H-0175 waits" in n for n in ctx.notes)
    assert autopilot.entries_this_week(ctx.root, ctx.now) == 2


def test_engine_cards_reach_the_gate_and_the_paper_book(
    folder: Path,
) -> None:
    from eulerlab.deploy import engine_book
    from eulerlab.validation import intraday

    spec = engine.RuleSpec.model_validate(GAP_FADE)
    (folder / "hypotheses" / "H-0999.yaml").write_text(
        writer.card_yaml(
            "H-0999", {"title": "t", "spec": spec}, day=date(2026, 11, 7), model="", tried_count=1
        )
    )
    assert intraday.supported("H-0999")
    assert not intraday.supported("H-0998")
    assert engine_book.is_engine_card("H-0999")


@pytest.mark.skipif(not os.environ.get("RULE_ENGINE_REPRO"), reason="needs the panel; ~3 minutes")
def test_engine_reproduces_research_176() -> None:
    legacy = {
        r["hypothesis"]: r
        for r in json.loads(Path("data/derived/daily_more.json").read_text())["runs"]
    }
    eng = engine.Engine(engine.Data())
    for h, spec in engine.reference_specs().items():
        out = eng.screen(spec)
        assert out["count"] == legacy[h].get("trades", legacy[h].get("positions"))
        assert out["net"] == legacy[h]["net"]
        assert out["halves"] == legacy[h]["halves"]
