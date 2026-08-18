"""Parsing screener.in tables — including the traps found in the real markup."""

from __future__ import annotations

from eulerlab.fundamentals.screener_parse import (
    company_name,
    parse_page,
    parse_section,
)

KEYED = """
<section id="quarters">
<table><thead><tr><th class="text"></th>
<th data-date-key="2024-03-31">Mar 2024</th>
<th data-date-key="2024-06-30">Jun 2024</th></tr></thead>
<tbody>
<tr><td class="text">Sales&nbsp;<span>+</span></td><td>1,234</td><td>2,345</td></tr>
<tr><td class="text">OPM %</td><td>18%</td><td>-</td></tr>
</tbody></table></section>
"""

# Shareholding tables carry no data-date-key - the trap that made them parse as
# zero rows on the first attempt.
UNKEYED = """
<section id="shareholding">
<table><thead><tr><th class="text"></th>
<th>Sep 2023</th><th>Dec 2023</th></tr></thead>
<tbody>
<tr><td class="text"><button>Promoters&nbsp;<span>+</span></button></td>
<td>50.27%</td><td>50.30%</td></tr>
</tbody></table></section>
"""


def test_parses_keyed_periods() -> None:
    cells = parse_section(KEYED, "quarters")
    sales = [c for c in cells if c.row_label == "Sales"]
    assert [c.period for c in sales] == ["2024-03-31", "2024-06-30"]
    assert [c.value for c in sales] == [1234.0, 2345.0]


def test_commas_and_percent_are_stripped() -> None:
    cells = parse_section(KEYED, "quarters")
    opm = [c for c in cells if c.row_label == "OPM %"]
    assert opm[0].value == 18.0


def test_a_dash_is_none_not_zero() -> None:
    """A missing value and a zero are different facts; conflating them
    silently corrupts any ratio computed downstream."""
    cells = parse_section(KEYED, "quarters")
    opm = [c for c in cells if c.row_label == "OPM %"]
    assert opm[1].value is None
    assert opm[1].raw == "-"


def test_row_labels_are_cleaned_of_markup_and_footnote_marks() -> None:
    cells = parse_section(KEYED, "quarters")
    assert "Sales" in {c.row_label for c in cells}
    assert not any("+" in c.row_label for c in cells)


def test_unkeyed_headers_fall_back_to_month_end() -> None:
    cells = parse_section(UNKEYED, "shareholding")
    assert [c.period for c in cells] == ["2023-09-30", "2023-12-31"]
    assert [c.value for c in cells] == [50.27, 50.30]


def test_promoters_label_survives_the_button_markup() -> None:
    cells = parse_section(UNKEYED, "shareholding")
    assert {c.row_label for c in cells} == {"Promoters"}


def test_a_missing_section_yields_no_rows_rather_than_raising() -> None:
    """One absent statement must not abort a 400-company run."""
    assert parse_section(KEYED, "balance-sheet") == []


def test_parse_page_collects_every_section() -> None:
    cells = parse_page(KEYED + UNKEYED)
    assert {c.section for c in cells} == {"quarters", "shareholding"}


def test_company_name_is_extracted() -> None:
    assert company_name("<h1> Reliance Industries Ltd </h1>") == "Reliance Industries Ltd"


def test_a_table_without_periods_is_skipped() -> None:
    assert (
        parse_section('<section id="ratios"><table><tr><td>x</td></tr></table></section>', "ratios")
        == []
    )
