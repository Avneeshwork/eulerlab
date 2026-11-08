"""Live-price paper: plan, open, close, reconcile (ADR-153). No network, no Kite."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.deploy import live_shadow as ls
from eulerlab.intraday import rule_engine as engine


def _spec(body: dict[str, Any]) -> engine.RuleSpec:
    return engine.RuleSpec.model_validate(body)


H0175 = {
    "kind": "intraday",
    "side": "short",
    "when": [
        {"signal": "gap", "op": ">=", "value": 0.02},
        {"signal": "delivery_ratio", "lag": 1, "op": "<=", "value": 0.8},
    ],
    "rank_by": {"signal": "gap"},
}


def test_books_from_config(tmp_path: Path, monkeypatch: Any) -> None:
    cfg = tmp_path / "live.yaml"
    cfg.write_text(
        "books:\n"
        "  - strategy: X-1\n"
        "    engine: {kind: intraday, side: short, when: [{signal: gap, op: '>=', value: 0.02},"
        " {signal: delivery_ratio, lag: 1, op: '<=', value: 0.8}], rank_by: {signal: gap}}\n"
        "  - strategy: X-2\n"
        "    engine: {kind: intraday, side: short, when: [{signal: results_morning}],"
        " rank_by: {signal: gap}}\n"
        "  - strategy: X-3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "card_spec", lambda h: None)
    shadowed, skipped = ls.books(cfg)
    assert [b.strategy for b in shadowed] == ["X-1"]
    assert "results_morning" in skipped["X-2"]
    assert "no engine block" in skipped["X-3"]


def test_shift_reads_one_session_earlier() -> None:
    spec = _spec(H0175)
    delivery = spec.when[1]
    assert ls._shift(delivery).lag == 0
    assert ls._at_open(spec.when[0]) and not ls._at_open(delivery)


def _book() -> dict[str, Any]:
    return {
        "strategy": "H-0175",
        "side": "short",
        "at_open": [{"op": ">=", "value": 0.02, "absolute": False}],
        "rank_at_open": True,
        "rank_order": "desc",
        "prev_close": {"AAA": 100.0, "BBB": 200.0, "CCC": 50.0, "DDD": 80.0},
        "candidates": {"AAA": None, "BBB": None, "CCC": None, "DDD": None},
    }


def _q(open_: float, bid: float, ask: float, last: float | None = None) -> dict[str, Any]:
    return {
        "ohlc": {"open": open_},
        "last_price": last or open_,
        "depth": {"buy": [{"price": bid}], "sell": [{"price": ask}]},
    }


def test_pick_applies_gap_ranks_and_records_the_spread() -> None:
    quotes = {
        "AAA": _q(103.0, 102.9, 103.1),  # gap 3%
        "BBB": _q(202.0, 201.9, 202.1),  # gap 1%: fails
        "CCC": _q(53.0, 52.95, 53.05),  # gap 6%: ranks first
    }
    out = ls.pick(_book(), quotes, "2026-11-09T09:15:20+05:30")
    assert [p["symbol"] for p in out["picks"]] == ["CCC", "AAA"]
    assert out["no_quote"] == ["DDD"]
    first = out["picks"][0]
    assert first["entry_quote"] == 52.95 and first["side"] == -1
    assert 18 < first["spread_bps"] < 19


def test_a_full_day_measures_slippage(tmp_path: Path) -> None:
    day = date(2026, 11, 9)
    folder = tmp_path / day.isoformat()
    folder.mkdir()
    import json

    (folder / "plan.json").write_text(json.dumps({"books": [_book()]}), encoding="utf-8")
    opened = ls.open_session(day, tmp_path, get=lambda s: {"AAA": _q(103.0, 102.9, 103.1)})
    assert opened["status"] == "ok"
    closed = ls.close_session(day, tmp_path, get=lambda s: {"AAA": _q(0, 100.9, 101.1)})
    assert closed["status"] == "ok"
    body = ls.reconcile(day, tmp_path, closes={"AAA": 101.0})
    trade = body["trades"][0]
    # backtest: short 103 -> 101 = +194.17 bps; achievable: sell 102.9, cover 101.1 = +174.93
    assert trade["backtest_bps"] == 194.17
    assert trade["achievable_bps"] == 174.93
    assert trade["slippage_bps"] == 19.25
    summary = ls.read_summary(tmp_path)["H-0175"]
    assert summary["sessions"] == 1 and summary["trades"] == 1


def test_a_dead_token_is_recorded_not_raised(tmp_path: Path) -> None:
    day = date(2026, 11, 9)
    (tmp_path / day.isoformat()).mkdir()
    import json

    (tmp_path / day.isoformat() / "plan.json").write_text(
        json.dumps({"books": [_book()]}), encoding="utf-8"
    )

    def dead(symbols: list[str]) -> dict[str, Any]:
        raise RuntimeError("no fresh Kite session")

    assert ls.open_session(day, tmp_path, get=dead)["status"] == "no quotes"
    assert ls.close_session(day, tmp_path, get=dead)["status"] == "no open"
    assert ls.reconcile(day, tmp_path, closes={"AAA": 1.0})["status"] == "incomplete"


def test_no_plan_means_no_sweep(tmp_path: Path) -> None:
    out = ls.open_session(date(2026, 11, 9), tmp_path, get=lambda s: {})
    assert out["status"] == "no plan"


def test_the_real_config_shadows_h0161_h0175_and_h0187_long() -> None:
    shadowed, skipped = ls.books()
    names = {b.strategy: b for b in shadowed}
    assert {"H-0161", "H-0187"} <= set(names)
    h0187 = names["H-0187"].spec
    assert h0187.side == "long" and names["H-0187"].source == "restated"
    assert "H-0168" in skipped  # needs that morning's results


def test_fund_units_are_never_candidates(tmp_path: Path) -> None:
    panel = tmp_path / "panel.jsonl"
    panel.write_text(
        '{"s": "NIFTYBEES", "isin": "INF204K014", "d": "2026-11-06"}\n'
        '{"s": "TCS", "isin": "INE467B010", "d": "2026-11-06"}\n',
        encoding="utf-8",
    )
    assert ls.fund_symbols(panel) == frozenset({"NIFTYBEES"})
