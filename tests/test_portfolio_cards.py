"""Portfolio cards through the gate (ADR-203): DP charges, the 2000-2014 join, the source."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from eulerlab.costs import router
from eulerlab.costs.schedule import Segment, Side


def _cost(side: Side, segment: Segment = Segment.EQUITY_DELIVERY) -> float:
    return router.fill_cost(
        venue="equity", price=500.0, quantity=200, side=side, day=date(2024, 6, 3), segment=segment
    )


def test_dp_charge_only_on_delivery_sells_and_only_inside_the_block() -> None:
    sell, buy = _cost(Side.SELL), _cost(Side.BUY)
    intraday_sell = _cost(Side.SELL, Segment.EQUITY_INTRADAY)
    with router.dp_charges():
        assert _cost(Side.SELL) == pytest.approx(sell + router.DP_CHARGE_INR)
        assert _cost(Side.BUY) == pytest.approx(buy)
        assert _cost(Side.SELL, Segment.EQUITY_INTRADAY) == pytest.approx(intraday_sell)
    assert _cost(Side.SELL) == pytest.approx(sell)  # off again after the block


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _row(d: str, s: str, isin: str, t: float, c: float = 100.0) -> dict[str, object]:
    return {"d": d, "s": s, "isin": isin, "o": c, "h": c, "l": c, "c": c, "v": 1.0, "t": t}


def test_history_join_renames_by_isin_masks_and_trims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.features import panel, panel_mask

    main, old = tmp_path / "main.jsonl", tmp_path / "old.jsonl"
    _write(
        main,
        [
            _row("2015-01-01", "NEWNAME", "INE000A010", 9e9),
            _row("2015-01-01", "TINY", "INE999Z010", 1.0),
        ],
    )
    _write(
        old,
        [
            _row("2003-06-02", "OLDNAME", "INE000A010", 5e9),  # before `start`
            _row("2004-06-01", "OLDNAME", "INE000A010", 5e9),
            _row("2004-06-01", "TINY", "INE999Z010", 1.0),
            _row("2004-06-02", "OLDNAME", "INE000A010", 5e9),
        ],
    )
    monkeypatch.setattr(panel, "read_panel", lambda: panel._parse_jsonl(main))
    monkeypatch.setattr(panel_mask, "HISTORY_PATH", old)

    class Mask:
        def wrong(self, isin: str, day: date) -> bool:
            return day == date(2004, 6, 2)  # a row a bhavcopy check proved wrong

    monkeypatch.setattr(panel_mask, "active", Mask)
    rows = panel.read_panel_with_history(date(2004, 1, 1), keep_top=1, always=())
    assert [(r.day, r.symbol) for r in rows] == [
        (date(2004, 6, 1), "NEWNAME"),  # under today's name; TINY trimmed
        (date(2015, 1, 1), "NEWNAME"),
    ]


def test_a_portfolio_card_is_found_by_its_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.validation import intraday

    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "hypotheses" / "H-9999.yaml").write_text(
        "id: H-9999\nconfigurations:\n- shape: portfolio_strategy\n  strategy: india_volatility_target_nifty\n"
    )
    (tmp_path / "hypotheses" / "H-9998.yaml").write_text(
        "id: H-9998\nconfigurations:\n- shape: rank_and_hold\n"
    )
    monkeypatch.chdir(tmp_path)
    assert intraday.portfolio_strategy("H-9999") == "india_volatility_target_nifty"
    assert intraday.portfolio_strategy("H-9998") is None
    assert intraday.supported("H-9999")
