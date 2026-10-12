"""The company page: what is read, what is computed, and what is left blank."""

from __future__ import annotations

import gzip
import json
from typing import Any

import pytest

from eulerlab.features import company as digest
from eulerlab.features import company_page as cp


def _columns(rows: list[tuple[str, str, str, float | None, str]]) -> dict[str, list[Any]]:
    """(section, row_label, period, value, raw) rows as Parquet-style columns."""
    return {
        "section": [r[0] for r in rows],
        "row_label": [r[1] for r in rows],
        "period": [r[2] for r in rows],
        "value": [r[3] for r in rows],
        "raw": [r[4] for r in rows],
        "consolidated": [True for _ in rows],
    }


QUARTERS = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
ROWS: list[tuple[str, str, str, float | None, str]] = [
    *[
        ("quarters", "Sales", q, v, "")
        for q, v in zip(QUARTERS, [100, 110, 120, 130, 150], strict=True)
    ],
    *[
        ("quarters", "Net Profit", q, v, "")
        for q, v in zip(QUARTERS, [10, 11, 12, 13, 5], strict=True)
    ],
    *[
        ("quarters", "EPS in Rs", q, v, "")
        for q, v in zip(QUARTERS, [1.0, 1.1, 1.2, 1.3, 0.5], strict=True)
    ],
    ("quarters", "Raw PDF", "2026-06-30", None, "link"),
    ("profit-loss", "Sales", "2025-03-31", 400.0, ""),
    ("profit-loss", "Sales", "2026-03-31", 500.0, ""),
    ("profit-loss", "Operating Profit", "2026-03-31", 100.0, ""),
    ("profit-loss", "Net Profit", "2025-03-31", -20.0, ""),
    ("profit-loss", "Net Profit", "2026-03-31", 50.0, ""),
    ("profit-loss", "EPS in Rs", "2026-03-31", 5.0, ""),
    ("balance-sheet", "Equity Capital", "2026-03-31", 10.0, ""),
    ("balance-sheet", "Reserves", "2026-03-31", 190.0, ""),
    ("balance-sheet", "Borrowings", "2026-03-31", 100.0, ""),
    ("cash-flow", "Free Cash Flow", "2026-03-31", 30.0, ""),
    ("shareholding", "Promoters", "2026-06-30", 51.5, ""),
    ("sector", "level_1", "", None, "Energy"),
    ("sector", "level_2", "", None, "Oil & Gas"),
    ("top_ratios", "Market Cap", "", None, "₹ 1,000 Cr."),
    ("top_ratios", "Stock P/E", "", None, "20.0"),
    ("index_membership", "Nifty 50", "", None, "Nifty 50"),
]


def test_tables_keep_source_order_and_sort_periods_and_drop_the_link_row() -> None:
    tables = cp.tables(_columns(ROWS))
    quarters = tables["quarters"]
    assert quarters["periods"] == QUARTERS
    assert [r["label"] for r in quarters["rows"]] == ["Sales", "Net Profit", "EPS in Rs"]
    # A period one row lacks is None, not zero and not shifted left.
    assert tables["profit-loss"]["rows"][1] == {
        "label": "Operating Profit",
        "values": [None, 100.0],
    }
    assert tables["ratios"] == {"periods": [], "rows": []}


def test_metrics_are_arithmetic_on_the_rows_shown() -> None:
    m = cp.metrics(cp.tables(_columns(ROWS)))
    assert m["debt_to_equity"] == pytest.approx(0.5)  # 100 / (10 + 190)
    assert m["net_margin"] == pytest.approx(0.10)
    assert m["operating_margin"] == pytest.approx(0.20)
    assert m["eps_ttm"] == pytest.approx(1.1 + 1.2 + 1.3 + 0.5)
    assert m["sales_growth"] == pytest.approx(0.25)
    # Same quarter a year earlier: Jun 26 against Jun 25.
    assert m["quarter_sales_growth"] == pytest.approx(0.5)
    assert m["quarter_profit_growth"] == pytest.approx(-0.5)
    assert m["quarter_period"] == "2026-06-30" and m["promoter_holding"] == 51.5


def test_a_missing_input_gives_none_never_zero() -> None:
    m = cp.metrics(cp.tables(_columns(ROWS)))
    # Last year was a loss: "growth" from -20 to 50 is not a percentage.
    assert m["profit_growth"] is None
    empty = cp.metrics(cp.tables(_columns([])))
    assert all(value is None for value in empty.values())
    # Fewer than four quarters of EPS is not a trailing-twelve-month figure.
    three = [r for r in ROWS if not (r[1] == "EPS in Rs" and r[2] < "2025-12-31")]
    assert cp.metrics(cp.tables(_columns(three)))["eps_ttm"] is None


def _company(symbol: str, industry: str, cap: float, pe: float | None) -> digest.Company:
    return digest.Company(symbol=symbol, industry=industry, market_cap=cap, pe=pe)


def test_peers_are_the_same_industry_largest_first_without_the_company_itself() -> None:
    held = {
        c.symbol: c
        for c in [
            _company("ME", "Oil", 50, 20),
            _company("BIG", "Oil", 900, 10),
            _company("MID", "Oil", 100, 30),
            _company("LOSS", "Oil", 10, None),
            _company("OTHER", "Banks", 999, 5),
        ]
    }
    found = cp.peers("ME", held, {"BIG": "Big Oil Ltd"})
    assert [r["symbol"] for r in found["rows"]] == ["BIG", "MID", "LOSS"]
    assert found["rows"][0]["name"] == "Big Oil Ltd"
    assert found["count"] == 4 and found["median_pe"] == 20 and found["pe_count"] == 3


def test_an_industry_median_needs_three_companies_with_earnings() -> None:
    held = {c.symbol: c for c in [_company("ME", "Oil", 50, 20), _company("B", "Oil", 9, 10)]}
    assert cp.peers("ME", held, {})["median_pe"] is None
    assert cp.peers("UNKNOWN", held, {})["rows"] == []


def test_news_is_matched_on_the_tag_not_on_text_and_newest_first() -> None:
    def line(guid: str, symbols: list[str], when: str) -> str:
        return json.dumps(
            {
                "guid": guid,
                "title": f"t-{guid}",
                "link": guid,
                "symbols": symbols,
                "event_time": when,
            }
        )

    blob = gzip.compress(
        "\n".join(
            [
                line("a", ["TCS"], "2026-10-01T00:00:00+00:00"),
                line("b", ["TCS", "INFY"], "2026-10-03T00:00:00+00:00"),
                line("c", ["INFY"], "2026-10-04T00:00:00+00:00"),
                # Mentions the symbol in the title only: not tagged, so not shown.
                json.dumps({"guid": "d", "title": 'about "TCS"', "symbols": ["WIPRO"]}),
                line("a", ["TCS"], "2026-10-01T00:00:00+00:00"),  # the same story twice
            ]
        ).encode()
    )
    assert [n["title"] for n in cp.news("TCS", [blob])] == ["t-b", "t-a"]


def test_price_block_takes_the_year_range_from_adjusted_closes() -> None:
    series = [(f"d{i}", float(i)) for i in range(1, 401)]
    block = cp.price_block(series, {"close": 800.0, "previous_close": 798.0, "volume": 5.0})
    # The last 252 sessions only, and from the adjusted series, not the raw bar.
    assert (block["low_52w"], block["high_52w"]) == (149.0, 400.0)
    assert block["close"] == 800.0 and block["day"] == "d400" and len(block["series"]) == 400
    assert cp.price_block([], {}) == {"series": []}


def test_build_names_what_is_not_held() -> None:
    page = cp.build(
        "ME",
        _columns(ROWS),
        companies={"ME": _company("ME", "Oil & Gas", 1e10, 20)},
        names={"ME": "Me Limited"},
        as_of="2026-10-11",
    )
    assert page["name"] == "Me Limited" and page["consolidated"] is True
    assert page["profile"]["sector_levels"] == ["Energy", "Oil & Gas"]
    assert page["profile"]["market_cap"] == 1_000 * digest.CRORE
    assert page["not_held"] == list(cp.NOT_HELD) and len(cp.NOT_HELD) == 4
    # Nothing on the page is made up for the panels that are not held.
    assert not {"analysts", "forecast", "estimates", "dcf", "about"} & set(page)


@pytest.mark.parametrize("bad", ["../.env", "a/b", "RELIANCE;rm", "x" * 30, ""])
def test_the_route_refuses_anything_that_is_not_a_symbol(bad: str) -> None:
    from eulerlab.api import company_routes

    assert company_routes.SYMBOL.fullmatch(bad.upper()) is None
    assert company_routes.SYMBOL.fullmatch("M&M") and company_routes.SYMBOL.fullmatch("BAJAJ-AUTO")
    assert company_routes.company(bad)["ok"] is False
